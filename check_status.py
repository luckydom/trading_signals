#!/usr/bin/env python3
"""Status check across all configured pairs with cointegration validation.

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
from src.features.cointegration import CointegrationTester
from src.utils.config import get_config


def main():
    parser = argparse.ArgumentParser(description="Check z-score status for all pairs with cointegration validation")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--show-all", action="store_true", help="Print all pairs, not just those above threshold")
    parser.add_argument("--threshold", type=float, default=None, help="Override |z| threshold")
    parser.add_argument("--sort", choices=["absz", "name", "confidence"], default="absz", help="Sort by abs z, name, or confidence")
    parser.add_argument("--require-coint", action="store_true", help="Only show cointegrated pairs")
    parser.add_argument("--coint-details", action="store_true", help="Show cointegration test details")
    args = parser.parse_args()

    config = get_config(args.config)

    exchange = config.get("exchange", "binance")
    timeframe = config.get("timeframe", "1h")
    z_threshold = float(args.threshold if args.threshold is not None else config.get("thresholds.z_in", 2.0))
    beta_window = int(config.get("windows.ols_beta", 200))
    zscore_window = int(config.get("windows.zscore", 100))

    # Initialize cointegration tester
    coint_tester = CointegrationTester(
        adf_threshold=config.get('adf_threshold', 0.05),
        min_half_life=config.get('min_half_life', 1.0),
        max_half_life=config.get('max_half_life', 30.0),
        lookback_window=config.get('cointegration_lookback', 500)
    )

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

        # Test cointegration
        coint_result = coint_tester.test_cointegration(
            y_data["close"],
            x_data["close"]
        )

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
                    "is_coint": coint_result["is_cointegrated"],
                    "coint_pvalue": coint_result.get("adf_pvalue", 1.0),
                    "half_life": coint_result.get("half_life"),
                    "confidence": 0,
                })
            continue

        latest = signals.loc[last_valid_idx]
        z = float(latest["zscore"]) if pd.notna(latest["zscore"]) else float("nan")

        # Calculate confidence score
        confidence = 0
        if coint_result["is_cointegrated"]:
            # Base confidence from cointegration
            if coint_result.get("adf_pvalue", 1.0) < 0.01:
                confidence += 40
            elif coint_result.get("adf_pvalue", 1.0) < 0.03:
                confidence += 30
            elif coint_result.get("adf_pvalue", 1.0) < 0.05:
                confidence += 20

            # Add confidence from z-score magnitude
            if abs(z) > 3.0:
                confidence += 40
            elif abs(z) > 2.5:
                confidence += 30
            elif abs(z) > 2.0:
                confidence += 20

            # Add confidence from half-life
            hl = coint_result.get("half_life")
            if hl and 2 <= hl <= 10:
                confidence += 20
            elif hl and 1 <= hl <= 20:
                confidence += 10

        rows.append({
            "name": name,
            "z": z,
            "beta": float(latest["beta"]),
            "y": y_symbol.split("/")[0],
            "x": x_symbol.split("/")[0],
            "y_price": float(latest["eth_price"]),
            "x_price": float(latest["btc_price"]),
            "ts": last_valid_idx,
            "is_coint": coint_result["is_cointegrated"],
            "coint_pvalue": coint_result.get("adf_pvalue", 1.0),
            "half_life": coint_result.get("half_life"),
            "confidence": confidence,
        })

    if args.sort == "absz":
        rows.sort(key=lambda r: abs(r["z"]), reverse=True)
    elif args.sort == "confidence":
        rows.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    else:
        rows.sort(key=lambda r: r["name"])

    # Filter by cointegration if requested
    if args.require_coint:
        rows = [r for r in rows if r.get("is_coint", False)]

    # Print header
    print("\n" + "="*100)
    print("PAIRS TRADING STATUS WITH COINTEGRATION VALIDATION")
    print("="*100)

    # Separate into categories
    tradeable = []
    cointegrated_waiting = []
    not_cointegrated = []

    for r in rows:
        is_coint = r.get("is_coint", False)
        z = r.get("z", float("nan"))

        if is_coint and not pd.isna(z) and abs(z) >= z_threshold:
            tradeable.append(r)
        elif is_coint:
            cointegrated_waiting.append(r)
        else:
            not_cointegrated.append(r)

    # Print tradeable opportunities
    if tradeable:
        print("\n🎯 TRADEABLE NOW (Cointegrated + Signal):")
        print("-" * 100)
        for r in tradeable:
            direction = "LONG" if r["z"] < 0 else "SHORT"
            coint_mark = "✅" if r.get("is_coint") else "❌"
            conf = r.get("confidence", 0)
            hl = r.get("half_life")
            hl_str = f"HL={hl:.1f}" if hl else "HL=N/A"

            print(f"{coint_mark} {r['name']}: {direction} | z={r['z']:.2f} | Conf={conf}% | "
                  f"β={r['beta']:.3f} | {hl_str} | p={r['coint_pvalue']:.3f} | "
                  f"{r['y']}={r['y_price']:.2f} {r['x']}={r['x_price']:.2f}")

    # Print cointegrated pairs waiting for signal
    if args.show_all or not tradeable:
        if cointegrated_waiting:
            print("\n⏳ COINTEGRATED (Waiting for Signal):")
            print("-" * 100)
            for r in cointegrated_waiting[:10]:  # Limit to top 10
                z_str = "nan" if pd.isna(r["z"]) else f"{r['z']:.2f}"
                hl = r.get("half_life")
                hl_str = f"HL={hl:.1f}" if hl else "HL=N/A"

                print(f"✅ {r['name']}: z={z_str} | β={r['beta']:.3f} | {hl_str} | "
                      f"p={r['coint_pvalue']:.3f}")

    # Show non-cointegrated count
    if not_cointegrated:
        print(f"\n❌ NON-COINTEGRATED: {len(not_cointegrated)} pairs failed cointegration tests")
        if args.coint_details and len(not_cointegrated) <= 5:
            for r in not_cointegrated[:5]:
                print(f"   • {r['name']}: p={r['coint_pvalue']:.3f}")

    # Summary
    print("\n" + "="*100)
    print("SUMMARY:")
    print(f"  Total pairs: {len(rows)}")
    print(f"  ✅ Cointegrated: {len(tradeable) + len(cointegrated_waiting)}")
    print(f"  🎯 Tradeable now: {len(tradeable)}")
    print(f"  ⏳ Waiting for signal: {len(cointegrated_waiting)}")
    print(f"  ❌ Not cointegrated: {len(not_cointegrated)}")

    if tradeable:
        print(f"\n🔥 Best opportunity: {tradeable[0]['name']} with {tradeable[0].get('confidence', 0)}% confidence")

    if not tradeable and not args.show_all:
        print(f"\n⚠️  No tradeable opportunities (cointegrated pairs with |z| >= {z_threshold})")


if __name__ == "__main__":
    main()
