#!/usr/bin/env python3
"""Debug script to check data and signals."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
import pandas as pd
import numpy as np

# Load data from cache
cache = DataCache()
btc_data = cache.load_ohlcv("binance", "BTC/USDT", "1h")
eth_data = cache.load_ohlcv("binance", "ETH/USDT", "1h")

print(f"BTC data shape: {btc_data.shape}")
print(f"ETH data shape: {eth_data.shape}")
print(f"Date range: {btc_data.index[0]} to {btc_data.index[-1]}")
print()

# Check for missing data
print("Checking for missing values:")
print(f"BTC missing: {btc_data['close'].isna().sum()}")
print(f"ETH missing: {eth_data['close'].isna().sum()}")
print()

# Calculate signals
print("Calculating signals...")
signals = SpreadCalculator.calculate_all_signals(
    btc_prices=btc_data['close'],
    eth_prices=eth_data['close'],
    beta_window=200,
    zscore_window=100
)

# Check signal quality
print(f"\nSignal DataFrame shape: {signals.shape}")
print(f"Non-NaN z-scores: {signals['zscore'].notna().sum()} / {len(signals)}")
print(f"First valid z-score at index: {signals['zscore'].first_valid_index()}")
print()

# Show last few rows
print("Last 5 rows of signals:")
print(signals[['btc_price', 'eth_price', 'beta', 'spread', 'zscore', 'spread_std']].tail())
print()

# Check why z-score might be NaN
print("Debugging z-score calculation:")
print(f"Beta NaN count: {signals['beta'].isna().sum()}")
print(f"Spread NaN count: {signals['spread'].isna().sum()}")
print(f"Spread_std NaN count: {signals['spread_std'].isna().sum()}")

# Check if we have enough data after calculations
valid_signals = signals.dropna(subset=['zscore'])
if len(valid_signals) > 0:
    print(f"\nValid signals after calculations: {len(valid_signals)}")
    print("Last valid z-score:")
    print(valid_signals[['zscore', 'beta', 'spread']].tail(1))
else:
    print("\nNo valid z-scores calculated!")
    print("This usually means we need more historical data.")

# Check minimum data requirements
min_required = 200 + 100  # beta_window + zscore_window
print(f"\nMinimum bars required: {min_required}")
print(f"Bars available: {len(btc_data)}")
if len(btc_data) < min_required:
    print(f"⚠️  Need {min_required - len(btc_data)} more bars for proper signal generation")