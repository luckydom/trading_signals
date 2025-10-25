"""Multi-pair backtest runner.

Usage:
  python -m src.backtest.multi --config config.yaml --out-dir reports --start-date 2024-01-01 --end-date 2024-12-31
"""

import sys
from pathlib import Path
from typing import List, Dict
import pandas as pd

# Add project root
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.utils.config import get_config
from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
from src.backtest.simulator import VectorizedBacktester
from src.backtest.report import render_single_pair_report, render_multi_report


def run_multi(config_path: str, start_date: str = None, end_date: str = None, out_dir: str = "reports", limit: int = None):
    config = get_config(config_path)
    cache = DataCache()
    pairs = [p for p in (config.get("pairs", []) or []) if p.get("enabled", True)]
    if limit:
        pairs = pairs[:limit]

    Path(out_dir).mkdir(parents=True, exist_ok=True)

    beta_w = int(config.get("windows.ols_beta", 200) or 200)
    z_w = int(config.get("windows.zscore", 100) or 100)

    z_in = float(config.get("thresholds.z_in", 2.0))
    z_out = float(config.get("thresholds.z_out", 0.5))
    z_stop = float(config.get("thresholds.z_stop", 3.5))

    bt = VectorizedBacktester(
        initial_capital=float(config.get("backtest.initial_capital", 100000)),
        fee_bps=float(config.get("costs.fee_bps", 10)),
        slippage_bps=float(config.get("costs.slippage_bps", 5)),
        target_sigma_usd=float(config.get("risk.target_sigma_usd", 200)),
        max_notional_per_leg=float(config.get("risk.max_notional_usd_per_leg", 25000)),
    )

    rows = []

    for pair in pairs:
        name = pair["name"]
        y_symbol = pair["asset_y"]
        x_symbol = pair["asset_x"]

        y_df = cache.load_ohlcv(config.get("exchange", "binance"), y_symbol, config.get("timeframe", "1h"))
        x_df = cache.load_ohlcv(config.get("exchange", "binance"), x_symbol, config.get("timeframe", "1h"))
        if y_df.empty or x_df.empty:
            continue

        # Apply date filters
        if start_date:
            start = pd.to_datetime(start_date, utc=True)
            y_df = y_df[y_df.index >= start]
            x_df = x_df[x_df.index >= start]
        if end_date:
            end = pd.to_datetime(end_date, utc=True)
            y_df = y_df[y_df.index <= end]
            x_df = x_df[x_df.index <= end]

        signals = SpreadCalculator.calculate_all_signals(
            btc_prices=x_df['close'],
            eth_prices=y_df['close'],
            beta_window=beta_w,
            zscore_window=z_w,
        )
        # Ensure we have some z values
        if signals['zscore'].notna().sum() < 5:
            continue

        results = bt.run_backtest(signals, z_in=z_in, z_out=z_out, z_stop=z_stop)

        # Save per-pair HTML
        pair_slug = "".join(c.lower() if c.isalnum() else "_" for c in name)
        out_html = str(Path(out_dir) / f"backtest_{pair_slug}.html")
        try:
            render_single_pair_report(signals, results, name, out_html, z_in=z_in, z_out=z_out, z_stop=z_stop)
        except Exception:
            pass

        row = {"pair": name}
        row.update(results.metrics)
        rows.append(row)

    if not rows:
        print("No pairs produced backtestable signals.")
        return

    summary = pd.DataFrame(rows)
    summary_path = Path(out_dir) / "multi_backtest_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"Summary CSV: {summary_path}")

    # Render summary HTML
    summary_html = Path(out_dir) / "multi_backtest_summary.html"
    try:
        render_multi_report(summary, str(summary_html))
        print(f"Summary HTML: {summary_html}")
    except Exception as e:
        print(f"Failed to render summary HTML: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run multi-pair backtests")
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--start-date')
    parser.add_argument('--end-date')
    parser.add_argument('--out-dir', default='reports')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()

    run_multi(
        config_path=args.config,
        start_date=args.start_date,
        end_date=args.end_date,
        out_dir=args.out_dir,
        limit=args.limit,
    )


if __name__ == '__main__':
    main()

