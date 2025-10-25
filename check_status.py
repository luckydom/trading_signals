#!/usr/bin/env python3
"""Status check across all configured pairs.

Defaults to printing only pairs where |z| >= thresholds.z_in. Use --show-all to
print every pair's latest z-score. Loads data from local cache.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import argparse
import pandas as pd

from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
from src.utils.config import get_config


def main():
    parser = argparse.ArgumentParser(description="Check z-score status for all pairs")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--show-all", action="store_true", help="Print all pairs, not just those above threshold")
    parser.add_argument("--threshold", type=float, default=None, help="Override |z| threshold")
    parser.add_argument("--sort", choices=["absz", "name"], default="absz", help="Sort by abs z or name")
    args = parser.parse_args()

    config = get_config(args.config)

    exchange = config.get("exchange", "binance")
    timeframe = config.get("timeframe", "1h")
    z_threshold = float(args.threshold if args.threshold is not None else config.get("thresholds.z_in", 2.0))
    beta_window = int(config.get("windows.ols_beta", 200))
    zscore_window = int(config.get("windows.zscore", 100))

    pairs = [p for p in (config.get("pairs", []) or []) if p.get("enabled", True)]
    if not pairs:
        pairs = [{"name": "BTC-ETH", "asset_y": "ETH/USDT", "asset_x": "BTC/USDT", "enabled": True}]

    # Preload unique symbols once
    symbols = set()
    for p in pairs:
        symbols.add(p["asset_y"])
        symbols.add(p["asset_x"])
    cache = DataCache()
    data_map = {sym: cache.load_ohlcv(exchange, sym, timeframe) for sym in symbols}

    rows = []
    for pair in pairs:
        name = pair["name"]
        y_symbol = pair["asset_y"]
        x_symbol = pair["asset_x"]
        y_data = data_map.get(y_symbol)
        x_data = data_map.get(x_symbol)
        if y_data is None or x_data is None or y_data.empty or x_data.empty:
            continue

        signals = SpreadCalculator.calculate_all_signals(
            btc_prices=x_data["close"],
            eth_prices=y_data["close"],
            beta_window=beta_window,
            zscore_window=zscore_window,
        )
        # Prefer the latest non-NaN z-score; the very last row can be NaN due to window edges
        last_valid_idx = signals["zscore"].last_valid_index()
        if last_valid_idx is None:
            # No computable z-score for this pair
            if args.show_all:
                # Emit a placeholder row so users can see which pairs lack data
                rows.append({
                    "name": name,
                    "z": float("nan"),
                    "beta": float(signals["beta"].dropna().iloc[-1]) if signals["beta"].notna().any() else float("nan"),
                    "y": y_symbol.split("/")[0],
                    "x": x_symbol.split("/")[0],
                    "y_price": float(y_data["close"].iloc[-1]),
                    "x_price": float(x_data["close"].iloc[-1]),
                    "ts": y_data.index[-1],
                })
            continue

        latest = signals.loc[last_valid_idx]
        z = float(latest["zscore"]) if pd.notna(latest["zscore"]) else float("nan")
        rows.append({
            "name": name,
            "z": z,
            "beta": float(latest["beta"]),
            "y": y_symbol.split("/")[0],
            "x": x_symbol.split("/")[0],
            "y_price": float(latest["eth_price"]),
            "x_price": float(latest["btc_price"]),
            "ts": last_valid_idx,
        })

    if args.sort == "absz":
        rows.sort(key=lambda r: abs(r["z"]), reverse=True)
    else:
        rows.sort(key=lambda r: r["name"])

    printed_any = False
    for r in rows:
        # When show-all, print even if z is NaN
        if not args.show_all:
            if pd.isna(r["z"]) or abs(r["z"]) < z_threshold:
                continue
        direction = ("N/A" if pd.isna(r["z"]) else ("LONG" if r["z"] < 0 else "SHORT"))
        z_str = ("  nan" if pd.isna(r["z"]) else f"{r['z']:.2f}")
        print(f"{r['name']}: {direction} spread | z={z_str} | beta={r['beta']:.3f} | "
              f"{r['y']}={r['y_price']:.2f} | {r['x']}={r['x_price']:.2f} | {r['ts']}")
        printed_any = True

    if not printed_any and not args.show_all:
        # Be explicit when no pairs exceed threshold
        print(f"No pairs with |z| >= {z_threshold}")


if __name__ == "__main__":
    main()
