#!/usr/bin/env python3
"""Quick status check of configured pairs.

Prints only pairs where |z-score| exceeds the configured entry threshold
(`thresholds.z_in`, default 2.0) in `config.yaml`.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd

from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
from src.utils.config import get_config


def main():
    config = get_config()

    exchange = config.get("exchange", "binance")
    timeframe = config.get("timeframe", "1h")
    z_threshold = float(config.get("thresholds.z_in", 2.0))
    beta_window = int(config.get("windows.ols_beta", 200))
    zscore_window = int(config.get("windows.zscore", 100))

    pairs = [p for p in (config.get("pairs", []) or []) if p.get("enabled", True)]
    if not pairs:
        # Fallback to legacy BTC/ETH if no pairs configured
        pairs = [{
            "name": "BTC-ETH",
            "asset_y": "ETH/USDT",
            "asset_x": "BTC/USDT",
            "enabled": True,
        }]

    cache = DataCache()
    printed_any = False

    for pair in pairs:
        name = pair["name"]
        y_symbol = pair["asset_y"]  # numerator
        x_symbol = pair["asset_x"]  # denominator

        y_data = cache.load_ohlcv(exchange, y_symbol, timeframe)
        x_data = cache.load_ohlcv(exchange, x_symbol, timeframe)

        if y_data.empty or x_data.empty:
            continue

        signals = SpreadCalculator.calculate_all_signals(
            btc_prices=x_data["close"],  # X
            eth_prices=y_data["close"],  # Y
            beta_window=beta_window,
            zscore_window=zscore_window,
        )

        latest = signals.iloc[-1]
        z = latest["zscore"]
        if pd.isna(z) or abs(z) <= z_threshold:
            continue

        printed_any = True
        direction = "LONG" if z < 0 else "SHORT"
        ts = signals.index[-1]
        print(
            f"{name}: {direction} spread | z={z:.2f} | beta={latest['beta']:.3f} | "
            f"{y_symbol.split('/')[0]}={latest['eth_price']:.2f} | {x_symbol.split('/')[0]}={latest['btc_price']:.2f} | {ts}"
        )

    # Optional: print nothing if none exceed. Keep silent per requirement.
    if not printed_any:
        pass


if __name__ == "__main__":
    main()
