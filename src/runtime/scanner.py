"""Main scanner orchestrator for hourly runs."""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional
import pandas as pd
# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.utils.config import get_config
from src.data.exchange import ExchangeClient
from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
from src.strategy.state import TradingStateMachine, SignalType
from src.strategy.sizing import VolatilityTargetingSizer
from src.runtime.tickets import TradeTicketGenerator
from src.runtime.notify import NotificationManager
from src.utils.logging import setup_logging


class Scanner:
    """Main scanner for running the trading strategy."""

    def __init__(self, config_path: str = "config.yaml", dry_run: bool = False):
        """Initialize scanner."""
        self.config = get_config(config_path)
        self.dry_run = dry_run

        # Setup logging
        self.logger = setup_logging(
            log_file=self.config.get("logging.file", "logs/scanner.log"),
            log_level=self.config.get("logging.level", "INFO")
        )

        # Initialize components
        self.exchange = ExchangeClient()
        self.cache = DataCache()
        self.state_machine = TradingStateMachine(
            z_in=self.config.get("thresholds.z_in", 2.0),
            z_out=self.config.get("thresholds.z_out", 0.5),
            z_stop=self.config.get("thresholds.z_stop", 3.5),
            state_file="data/state.json"
        )
        self.sizer = VolatilityTargetingSizer(
            target_sigma_usd=self.config.get("risk.target_sigma_usd", 200),
            max_notional_per_leg=self.config.get("risk.max_notional_usd_per_leg", 25000),
            fee_bps=self.config.get("costs.fee_bps", 10),
            slippage_bps=self.config.get("costs.slippage_bps", 5)
        )
        self.ticket_gen = TradeTicketGenerator()
        self.notifier = NotificationManager(self.config)

        self.logger.info("Scanner initialized")

    def run(self):
        """Run the scanner."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.logger.info(f"Starting scanner run: {run_id}")

        try:
            # Step 1: Update data cache
            symbols = self.config.get("symbols.base", ["BTC/USDT", "ETH/USDT"])
            timeframe = self.config.get("timeframe", "1h")

            self.logger.info("Updating data cache...")
            data = self.cache.update_cache(
                self.exchange,
                symbols,
                timeframe,
                lookback_bars=self.config.get("filters.min_bars_required", 250)
            )

            if not data or len(data) != 2:
                self.logger.error("Failed to fetch required data")
                return

            # Extract BTC and ETH data
            btc_data = data[symbols[0]]
            eth_data = data[symbols[1]]

            if btc_data.empty or eth_data.empty:
                self.logger.error("Empty data received")
                return

            # Step 2: Calculate signals
            self.logger.info("Calculating signals...")
            signals = SpreadCalculator.calculate_all_signals(
                btc_prices=btc_data['close'],
                eth_prices=eth_data['close'],
                beta_window=self.config.get("windows.ols_beta", 200),
                zscore_window=self.config.get("windows.zscore", 100)
            )

            # Add liquidity metrics
            btc_with_liquidity = self.cache.calculate_liquidity_metrics(btc_data)
            eth_with_liquidity = self.cache.calculate_liquidity_metrics(eth_data)

            # Get latest values
            latest = signals.iloc[-1]
            latest_btc_adv = btc_with_liquidity['adv_usd'].iloc[-1]
            latest_eth_adv = eth_with_liquidity['adv_usd'].iloc[-1]

            self.logger.info(f"Latest Z-score: {latest['zscore']:.2f}, Beta: {latest['beta']:.3f}")

            # Step 3: Check filters
            min_adv = self.config.get("filters.min_adv_usd", 5_000_000)
            if latest_btc_adv < min_adv or latest_eth_adv < min_adv:
                self.logger.warning(f"ADV filter not met: BTC={latest_btc_adv:.0f}, ETH={latest_eth_adv:.0f}")
                return

            # Step 4: Process signal through state machine
            signal = self.state_machine.process_tick(
                timestamp=signals.index[-1],
                zscore=latest['zscore'],
                beta=latest['beta'],
                spread=latest['spread'],
                btc_price=latest['btc_price'],
                eth_price=latest['eth_price']
            )

            # Step 5: Generate trade ticket if signal
            if signal.signal_type != SignalType.NO_ACTION:
                self.logger.info(f"Signal generated: {signal.signal_type.value} - {signal.reason}")

                # Calculate position size
                position_size = self.sizer.calculate_position_size(
                    beta=signal.beta,
                    spread_std=latest['spread_std'],
                    btc_price=signal.btc_price,
                    eth_price=signal.eth_price,
                    btc_adv_usd=latest_btc_adv,
                    eth_adv_usd=latest_eth_adv
                )

                # Generate ticket
                ticket = self.ticket_gen.generate_ticket(signal, position_size, funding_info={})

                # Save ticket
                ticket_file = self.ticket_gen.save_ticket(ticket, run_id)
                self.logger.info(f"Trade ticket saved: {ticket_file}")

                # Send notification
                if not self.dry_run:
                    self.notifier.send_trade_signal(signal, position_size)
                    self.logger.info("Notification sent")
                else:
                    self.logger.info("DRY RUN - Notification skipped")

                # Print ticket to console
                print("\n" + "="*60)
                print(ticket)
                print("="*60 + "\n")
            else:
                self.logger.info("No trading signal generated")

            # Step 6: Log metrics
            metrics = SpreadCalculator.calculate_signal_quality_metrics(signals)
            self.logger.info(f"Signal quality metrics: {json.dumps(metrics, indent=2)}")

            # Save run log
            self._save_run_log(run_id, signals, signal)

        except Exception as e:
            self.logger.error(f"Scanner error: {e}", exc_info=True)
            raise

    def _save_run_log(self, run_id: str, signals: pd.DataFrame, signal):
        """Save run log for debugging and analysis."""
        log_dir = Path("logs/runs")
        log_dir.mkdir(parents=True, exist_ok=True)

        log_data = {
            'run_id': run_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'latest_zscore': float(signals['zscore'].iloc[-1]),
            'latest_beta': float(signals['beta'].iloc[-1]),
            'latest_spread': float(signals['spread'].iloc[-1]),
            'signal_type': signal.signal_type.value,
            'position_state': self.state_machine.current_state.value,
            'config': {
                'z_in': self.config.get("thresholds.z_in"),
                'z_out': self.config.get("thresholds.z_out"),
                'z_stop': self.config.get("thresholds.z_stop")
            }
        }

        log_file = log_dir / f"run_{run_id}.json"
        with open(log_file, 'w') as f:
            json.dump(log_data, f, indent=2)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Run trading scanner')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    args = parser.parse_args()

    scanner = Scanner(config_path=args.config, dry_run=args.dry_run)
    scanner.run()


if __name__ == "__main__":
    main()