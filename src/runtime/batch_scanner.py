"""Batch scanner to process all configured pairs and send a single email per run.

Usage examples:
  DEV_MODE=true python -m src.runtime.batch_scanner --dry-run --use-cache-only
  python -m src.runtime.batch_scanner --use-cache-only --ignore-adv

Flags largely mirror Scanner, but operate across all enabled pairs in config.yaml.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List
import time
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


def safe_name(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name)


def run_batch(
    config_path: str,
    dry_run: bool = False,
    use_cache_only: bool = False,
    level_trigger: bool = False,
    ignore_adv: bool = False,
    test_discord: bool = False,
):
    config = get_config(config_path)
    logger = setup_logging(
        log_file=config.get("logging.file", "logs/scanner.log"),
        log_level=config.get("logging.level", "INFO")
    )

    exchange_name = config.get("exchange", "binance")
    timeframe = config.get("timeframe", "1h")
    z_in = config.get("thresholds.z_in", 2.0)

    notifier = NotificationManager(config)

    # If only testing Discord webhook, send and exit (no market access required)
    if test_discord:
        ok = False
        if notifier.discord_webhook:
            ok = notifier._send_discord("Test notification from trading_signals batch scanner ✅")
        print("Discord webhook sent" if ok else "Discord webhook failed or not configured")
        return

    exchange = None if use_cache_only else ExchangeClient()
    cache = DataCache()
    sizer = VolatilityTargetingSizer(
        target_sigma_usd=config.get("risk.target_sigma_usd", 200),
        max_notional_per_leg=config.get("risk.max_notional_usd_per_leg", 25000),
        fee_bps=config.get("costs.fee_bps", 10),
        slippage_bps=config.get("costs.slippage_bps", 5)
    )
    ticket_gen = TradeTicketGenerator()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info(f"Starting batch scanner run: {run_id}")

    tickets: List[str] = []
    # Per-message throttle seconds (Discord typical limits are strict; be conservative)
    throttle_sec = float(config.get("notifications.throttle_seconds", 0.75) or 0.75)

    pairs = [p for p in (config.get("pairs", []) or []) if p.get("enabled", True)]

    # Optimize: update cache once per unique symbol
    symbols = set()
    for p in pairs:
        symbols.add(p["asset_y"])  # numerator
        symbols.add(p["asset_x"])  # denominator

    if use_cache_only:
        data_map = {}
        for sym in symbols:
            data_map[sym] = cache.load_ohlcv(exchange_name, sym, timeframe)
    else:
        # Update all symbols in one call to minimize exchange requests
        updated = cache.update_cache(exchange, sorted(symbols), timeframe,
                                     lookback_bars=config.get("filters.min_bars_required", 250))
        data_map = updated

    for pair in pairs:
        name = pair["name"]
        y_symbol = pair["asset_y"]
        x_symbol = pair["asset_x"]
        pair_state_file = f"data/state_{safe_name(name)}.json"

        try:
            # Retrieve preloaded data
            y_df = data_map.get(y_symbol, pd.DataFrame())
            x_df = data_map.get(x_symbol, pd.DataFrame())

            if y_df.empty or x_df.empty:
                logger.warning(f"No data for {name}")
                continue

            # Signals
            signals = SpreadCalculator.calculate_all_signals(
                btc_prices=x_df['close'],  # X
                eth_prices=y_df['close'],  # Y
                beta_window=config.get("windows.ols_beta", 200),
                zscore_window=config.get("windows.zscore", 100)
            )

            latest = signals.iloc[-1]

            # Liquidity/ADV check
            y_liq = cache.calculate_liquidity_metrics(y_df)
            x_liq = cache.calculate_liquidity_metrics(x_df)
            y_adv = y_liq['adv_usd'].iloc[-1]
            x_adv = x_liq['adv_usd'].iloc[-1]
            min_adv = config.get("filters.min_adv_usd", 5_000_000)
            if not ignore_adv and (y_adv < min_adv or x_adv < min_adv):
                logger.info(f"{name}: ADV filter not met (Y={y_adv:.0f}, X={x_adv:.0f})")
                continue

            # State machine per pair
            sm = TradingStateMachine(
                z_in=config.get("thresholds.z_in", 2.0),
                z_out=config.get("thresholds.z_out", 0.5),
                z_stop=config.get("thresholds.z_stop", 3.5),
                state_file=pair_state_file
            )
            if sm.previous_zscore is None and len(signals) >= 2:
                prev = signals['zscore'].iloc[-2]
                if pd.notna(prev):
                    sm.previous_zscore = float(prev)

            signal = sm.process_tick(
                timestamp=signals.index[-1],
                zscore=latest['zscore'],
                beta=latest['beta'],
                spread=latest['spread'],
                btc_price=latest['btc_price'],
                eth_price=latest['eth_price']
            )

            # Optional level trigger
            if (signal.signal_type == SignalType.NO_ACTION and level_trigger and
                sm.current_state == sm.current_state.NEUTRAL and pd.notna(latest['zscore'])):
                if abs(latest['zscore']) >= z_in:
                    stype = SignalType.ENTER_SHORT_SPREAD if latest['zscore'] > 0 else SignalType.ENTER_LONG_SPREAD
                    from src.strategy.state import TradingSignal, PositionState
                    new_state = PositionState.SHORT_SPREAD if stype == SignalType.ENTER_SHORT_SPREAD else PositionState.LONG_SPREAD
                    signal = TradingSignal(
                        timestamp=signals.index[-1],
                        signal_type=stype,
                        zscore=float(latest['zscore']),
                        beta=float(latest['beta']),
                        spread=float(latest['spread']),
                        reason=f"Level trigger |z| >= {z_in}",
                        btc_price=float(latest['btc_price']),
                        eth_price=float(latest['eth_price']),
                        previous_state=sm.current_state,
                        new_state=new_state
                    )

            if signal.signal_type != SignalType.NO_ACTION:
                # Size
                pos = sizer.calculate_position_size(
                    beta=signal.beta,
                    spread_std=float(latest.get('spread_std', 0) or 0),
                    btc_price=signal.btc_price,
                    eth_price=signal.eth_price,
                    btc_adv_usd=x_adv,
                    eth_adv_usd=y_adv
                )
                # Ticket with correct asset labels
                ticket = ticket_gen.generate_ticket(
                    signal, pos, y_symbol=y_symbol, x_symbol=x_symbol, funding_info={}
                )
                ticket_file = ticket_gen.save_ticket(ticket, run_id)
                logger.info(f"{name}: ticket saved -> {ticket_file}")
                tickets.append(f"{name}\n{ticket}")

                # Send one message per ticket with simple throttling to respect webhook limits
                if not dry_run:
                    sent_any = False
                    if notifier.slack_enabled and notifier.slack_webhook:
                        sent_any = notifier._send_slack(ticket) or sent_any
                        time.sleep(throttle_sec)
                    if notifier.discord_webhook:
                        # Attempt send; if it fails due to rate limit, do a simple backoff
                        ok = notifier._send_discord(ticket)
                        if not ok:
                            time.sleep(max(throttle_sec * 2, 2.0))
                            notifier._send_discord(ticket)
                        time.sleep(throttle_sec)
                    if not sent_any and not notifier.discord_webhook:
                        # Fallback to console if no channels configured
                        print(ticket)
            else:
                logger.info(f"{name}: no signal")

        except Exception as e:
            logger.error(f"{name}: error {e}")
            continue

    # Previously: aggregated summary. Now we send per ticket above.

    # Console summary
    print(f"Tickets this run: {len(tickets)}")
    if tickets:
        print("Pairs:", ", ".join(t.split('\n',1)[0] for t in tickets))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run batch scanner across all pairs')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--use-cache-only', action='store_true')
    parser.add_argument('--level-trigger', action='store_true')
    parser.add_argument('--ignore-adv', action='store_true')
    parser.add_argument('--test-discord', action='store_true', help='Send a test Discord message and exit')
    args = parser.parse_args()

    run_batch(
        config_path=args.config,
        dry_run=args.dry_run,
        use_cache_only=args.use_cache_only,
        level_trigger=args.level_trigger,
        ignore_adv=args.ignore_adv,
        test_discord=args.test_discord,
    )


if __name__ == '__main__':
    main()
