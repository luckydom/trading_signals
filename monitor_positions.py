#!/usr/bin/env python3
"""Monitor open positions and generate exit signals.

This script tracks your open positions and alerts when exit conditions are met:
- Exit when |z-score| <= 0.5 (mean reversion complete)
- Stop loss when |z-score| >= 3.5 (spread diverging further)
- Optional: Exit when position moves against you (z-score crosses zero)
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

sys.path.append(str(Path(__file__).parent))

from src.utils.config import get_config
from src.data.cache import DataCache
from src.data.exchange import ExchangeClient
from src.features.spread import SpreadCalculator
from src.features.cointegration import CointegrationTester


class Position:
    """Represents an open position."""

    def __init__(self, pair: str, direction: str, entry_z: float, entry_date: str,
                 entry_prices: Dict[str, float], quantities: Dict[str, float]):
        self.pair = pair
        self.direction = direction  # "LONG" or "SHORT" spread
        self.entry_z = entry_z
        self.entry_date = entry_date
        self.entry_prices = entry_prices
        self.quantities = quantities
        self.is_open = True

    def to_dict(self):
        return {
            'pair': self.pair,
            'direction': self.direction,
            'entry_z': self.entry_z,
            'entry_date': self.entry_date,
            'entry_prices': self.entry_prices,
            'quantities': self.quantities,
            'is_open': self.is_open
        }

    @classmethod
    def from_dict(cls, data):
        pos = cls(
            data['pair'], data['direction'], data['entry_z'],
            data['entry_date'], data['entry_prices'], data['quantities']
        )
        pos.is_open = data.get('is_open', True)
        return pos


class PositionMonitor:
    """Monitor open positions for exit signals."""

    def __init__(self, config_path: str = "config.yaml", use_cache_only: bool = False):
        self.config = get_config(config_path)
        self.positions_file = "data/open_positions.json"
        self.positions = self.load_positions()
        self.use_cache_only = use_cache_only

        # Exit thresholds
        self.exit_threshold = self.config.get("thresholds.z_out", 0.5)
        self.stop_loss_threshold = self.config.get("thresholds.z_stop", 3.5)

        # Initialize components
        self.cache = DataCache()
        self.exchange = None if use_cache_only else ExchangeClient()
        self.coint_tester = CointegrationTester()

    def load_positions(self) -> List[Position]:
        """Load open positions from file."""
        if not Path(self.positions_file).exists():
            return []

        with open(self.positions_file, 'r') as f:
            data = json.load(f)

        return [Position.from_dict(p) for p in data if p.get('is_open', True)]

    def save_positions(self):
        """Save positions to file."""
        data = [p.to_dict() for p in self.positions]
        with open(self.positions_file, 'w') as f:
            json.dump(data, f, indent=2)

    def add_position(self, pair: str, direction: str, entry_z: float,
                     entry_prices: Dict[str, float], quantities: Dict[str, float]):
        """Add a new position to monitor."""
        pos = Position(
            pair=pair,
            direction=direction,
            entry_z=entry_z,
            entry_date=datetime.utcnow().isoformat(),
            entry_prices=entry_prices,
            quantities=quantities
        )
        self.positions.append(pos)
        self.save_positions()
        print(f"✅ Added position: {pair} {direction} at z={entry_z:.2f}")

    def check_exit_signals(self):
        """Check all open positions for exit signals."""
        if not self.positions:
            print("No open positions to monitor")
            return

        exchange_name = self.config.get("exchange", "binance")
        timeframe = self.config.get("timeframe", "1h")

        print("\n" + "="*80)
        print("POSITION MONITOR - EXIT SIGNAL CHECK")
        print("="*80)
        print(f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")

        # Fetch fresh market data if not using cache only
        if self.exchange:
            print("📡 Fetching current market prices...\n")

        for position in self.positions:
            if not position.is_open:
                continue

            # Parse pair (e.g., "ATOM-SOL" -> "ATOM/USDT", "SOL/USDT")
            symbols = position.pair.split('-')
            if len(symbols) != 2:
                print(f"❌ Invalid pair format: {position.pair}")
                continue

            symbol1 = f"{symbols[0]}/USDT"
            symbol2 = f"{symbols[1]}/USDT"

            # Fetch fresh data or load from cache
            if self.exchange:
                try:
                    # Fetch fresh data - enough bars for signal calculation
                    # Need more data for beta (200) + zscore (100) calculations
                    df1 = self.exchange.fetch_ohlcv_bars(
                        symbol=symbol1,
                        timeframe=timeframe,
                        bars=500
                    )
                    df2 = self.exchange.fetch_ohlcv_bars(
                        symbol=symbol2,
                        timeframe=timeframe,
                        bars=500
                    )

                    # Save to cache for backup
                    if not df1.empty:
                        self.cache.save_ohlcv(df1, exchange_name, symbol1, timeframe, append=True)
                    if not df2.empty:
                        self.cache.save_ohlcv(df2, exchange_name, symbol2, timeframe, append=True)

                except Exception as e:
                    print(f"⚠️  Error fetching fresh data for {position.pair}: {e}")
                    print("   Falling back to cached data...")
                    df1 = self.cache.load_ohlcv(exchange_name, symbol1, timeframe)
                    df2 = self.cache.load_ohlcv(exchange_name, symbol2, timeframe)
            else:
                # Use cache only mode
                df1 = self.cache.load_ohlcv(exchange_name, symbol1, timeframe)
                df2 = self.cache.load_ohlcv(exchange_name, symbol2, timeframe)

            if df1 is None or df2 is None or df1.empty or df2.empty:
                print(f"⚠️  No data for {position.pair}")
                continue

            # Align dataframes by timestamp
            common_index = df1.index.intersection(df2.index)
            if len(common_index) < 200:  # Need enough data for calculations
                print(f"⚠️  Insufficient overlapping data for {position.pair}")
                continue

            df1_aligned = df1.loc[common_index]
            df2_aligned = df2.loc[common_index]

            # Calculate current signals
            signals = SpreadCalculator.calculate_all_signals(
                btc_prices=df1_aligned['close'],  # First asset
                eth_prices=df2_aligned['close'],  # Second asset
                beta_window=self.config.get("windows.ols_beta", 200),
                zscore_window=self.config.get("windows.zscore", 100)
            )

            # Get latest z-score
            latest = signals.iloc[-1]
            current_z = float(latest['zscore']) if pd.notna(latest['zscore']) else None

            if current_z is None:
                print(f"⚠️  {position.pair}: Cannot calculate z-score")
                continue

            # Get current prices - fetch latest if available
            if self.exchange:
                try:
                    # Fetch real-time spot prices
                    ticker1 = self.exchange.exchange.fetch_ticker(symbol1)
                    ticker2 = self.exchange.exchange.fetch_ticker(symbol2)
                    current_prices = {
                        symbols[0]: ticker1['last'],
                        symbols[1]: ticker2['last']
                    }
                except:
                    # Fallback to prices from OHLCV data
                    current_prices = {
                        symbols[0]: float(df1_aligned['close'].iloc[-1]),
                        symbols[1]: float(df2_aligned['close'].iloc[-1])
                    }
            else:
                current_prices = {
                    symbols[0]: float(df1_aligned['close'].iloc[-1]),
                    symbols[1]: float(df2_aligned['close'].iloc[-1])
                }

            # Calculate P&L
            pnl = self.calculate_pnl(position, current_prices)

            # Check exit conditions
            exit_signal = self.check_exit_conditions(position, current_z)

            # Display status
            self.display_position_status(position, current_z, current_prices, pnl, exit_signal)

    def check_exit_conditions(self, position: Position, current_z: float) -> Optional[str]:
        """Check if position should be exited."""

        # For LONG spread (entered when z < -2)
        if position.direction == "LONG":
            # Exit when z returns to near 0 (mean reversion complete)
            if current_z >= -self.exit_threshold:
                return f"✅ EXIT SIGNAL: Mean reversion complete (z={current_z:.2f} >= -{self.exit_threshold})"

            # Stop loss if spread diverges further
            if current_z <= -self.stop_loss_threshold:
                return f"🛑 STOP LOSS: Spread diverging (z={current_z:.2f} <= -{self.stop_loss_threshold})"

            # Optional: Exit if z crosses to positive (trend reversal)
            if current_z > 0:
                return f"⚠️  REVERSAL: Z-score crossed zero (z={current_z:.2f})"

        # For SHORT spread (entered when z > 2)
        elif position.direction == "SHORT":
            # Exit when z returns to near 0
            if current_z <= self.exit_threshold:
                return f"✅ EXIT SIGNAL: Mean reversion complete (z={current_z:.2f} <= {self.exit_threshold})"

            # Stop loss if spread diverges further
            if current_z >= self.stop_loss_threshold:
                return f"🛑 STOP LOSS: Spread diverging (z={current_z:.2f} >= {self.stop_loss_threshold})"

            # Optional: Exit if z crosses to negative
            if current_z < 0:
                return f"⚠️  REVERSAL: Z-score crossed zero (z={current_z:.2f})"

        return None

    def calculate_pnl(self, position: Position, current_prices: Dict[str, float]) -> Dict[str, float]:
        """Calculate P&L for a position."""
        symbols = position.pair.split('-')

        # Calculate P&L for each leg
        pnl_leg1 = 0
        pnl_leg2 = 0

        if symbols[0] in position.quantities:
            qty1 = position.quantities[symbols[0]]
            entry_price1 = position.entry_prices[symbols[0]]
            current_price1 = current_prices[symbols[0]]

            if position.direction == "SHORT":
                # First asset is shorted in SHORT spread
                pnl_leg1 = -qty1 * (current_price1 - entry_price1)
            else:
                # First asset is long in LONG spread
                pnl_leg1 = qty1 * (current_price1 - entry_price1)

        if symbols[1] in position.quantities:
            qty2 = position.quantities[symbols[1]]
            entry_price2 = position.entry_prices[symbols[1]]
            current_price2 = current_prices[symbols[1]]

            if position.direction == "SHORT":
                # Second asset is long in SHORT spread
                pnl_leg2 = qty2 * (current_price2 - entry_price2)
            else:
                # Second asset is shorted in LONG spread
                pnl_leg2 = -qty2 * (current_price2 - entry_price2)

        total_pnl = pnl_leg1 + pnl_leg2

        # Calculate percentage return
        total_entry_value = abs(position.quantities.get(symbols[0], 0) * position.entry_prices.get(symbols[0], 0)) + \
                           abs(position.quantities.get(symbols[1], 0) * position.entry_prices.get(symbols[1], 0))

        pnl_pct = (total_pnl / total_entry_value * 100) if total_entry_value > 0 else 0

        return {
            'leg1_pnl': pnl_leg1,
            'leg2_pnl': pnl_leg2,
            'total_pnl': total_pnl,
            'pnl_pct': pnl_pct
        }

    def display_position_status(self, position: Position, current_z: float,
                                current_prices: Dict[str, float], pnl: Dict[str, float],
                                exit_signal: Optional[str]):
        """Display position status."""
        symbols = position.pair.split('-')

        print(f"\n{'='*60}")
        print(f"📊 {position.pair} - {position.direction} SPREAD")
        print(f"{'='*60}")

        print(f"Entry Date: {position.entry_date}")
        print(f"Entry Z-score: {position.entry_z:.2f}")
        print(f"Current Z-score: {current_z:.2f}")
        print(f"Z-score Change: {current_z - position.entry_z:.2f}")

        print(f"\nPrice Movement:")
        for symbol in symbols:
            if symbol in position.entry_prices:
                entry = position.entry_prices[symbol]
                current = current_prices[symbol]
                change_pct = (current - entry) / entry * 100
                print(f"  {symbol}: ${entry:.2f} → ${current:.2f} ({change_pct:+.1f}%)")

        print(f"\nP&L:")
        print(f"  Leg 1 ({symbols[0]}): ${pnl['leg1_pnl']:+.2f}")
        print(f"  Leg 2 ({symbols[1]}): ${pnl['leg2_pnl']:+.2f}")
        print(f"  Total: ${pnl['total_pnl']:+.2f} ({pnl['pnl_pct']:+.1f}%)")

        if exit_signal:
            print(f"\n{exit_signal}")
            print("🔔 ACTION REQUIRED: Close both legs of the position")
        else:
            print(f"\n⏳ HOLD: No exit signal yet")
            print(f"   Exit when: |z| <= {self.exit_threshold}")
            print(f"   Stop loss: |z| >= {self.stop_loss_threshold}")


def main():
    """Main function for CLI usage."""
    import argparse

    parser = argparse.ArgumentParser(description='Monitor open positions for exit signals')
    parser.add_argument('--add', nargs=5, metavar=('PAIR', 'DIR', 'Z', 'PRICES', 'QTY'),
                       help='Add position: ATOM-SOL SHORT 2.32 {"ATOM":3.15,"SOL":191.89} {"ATOM":80.13,"SOL":0.537}')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--use-cache-only', action='store_true',
                       help='Use cached data only, do not fetch fresh prices')

    args = parser.parse_args()

    monitor = PositionMonitor(args.config, use_cache_only=args.use_cache_only)

    if args.add:
        # Parse add position arguments
        pair = args.add[0]
        direction = args.add[1]
        entry_z = float(args.add[2])
        entry_prices = json.loads(args.add[3])
        quantities = json.loads(args.add[4])

        monitor.add_position(pair, direction, entry_z, entry_prices, quantities)
    else:
        # Check exit signals for all positions
        monitor.check_exit_signals()


if __name__ == "__main__":
    main()