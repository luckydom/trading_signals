#!/usr/bin/env python3
"""Analyze backtest data to understand trading opportunities."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
import numpy as np
import pandas as pd

# Load data
cache = DataCache()
btc_data = cache.load_ohlcv("binance", "BTC/USDT", "1h")
eth_data = cache.load_ohlcv("binance", "ETH/USDT", "1h")

# Calculate signals
signals = SpreadCalculator.calculate_all_signals(
    btc_prices=btc_data['close'],
    eth_prices=eth_data['close'],
    beta_window=200,
    zscore_window=100
)

# Filter valid z-scores
valid_z = signals['zscore'].dropna()

print("="*60)
print("BACKTEST DATA ANALYSIS")
print("="*60)
print(f"Data Range: {signals.index[0]} to {signals.index[-1]}")
print(f"Total Bars: {len(signals)}")
print(f"Valid Z-scores: {len(valid_z)} ({len(valid_z)/len(signals)*100:.1f}%)")
print()

print("Z-SCORE STATISTICS:")
print(f"  Mean: {valid_z.mean():.3f}")
print(f"  Std Dev: {valid_z.std():.3f}")
print(f"  Min: {valid_z.min():.3f}")
print(f"  Max: {valid_z.max():.3f}")
print()

# Check for signal crossings
z_prev = signals['zscore'].shift(1)
long_signals = (z_prev >= -2.0) & (signals['zscore'] < -2.0)
short_signals = (z_prev <= 2.0) & (signals['zscore'] > 2.0)

print("SIGNAL GENERATION:")
print(f"  Long signals (z < -2.0): {long_signals.sum()}")
print(f"  Short signals (z > 2.0): {short_signals.sum()}")
print()

# Z-score distribution
print("Z-SCORE DISTRIBUTION:")
thresholds = [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3]
for i in range(len(thresholds)-1):
    count = ((valid_z >= thresholds[i]) & (valid_z < thresholds[i+1])).sum()
    pct = count / len(valid_z) * 100
    bar = "█" * int(pct/2)
    print(f"  {thresholds[i]:>4.1f} to {thresholds[i+1]:>4.1f}: {count:4d} ({pct:5.1f}%) {bar}")

# Check extremes
print()
print("EXTREME VALUES:")
extreme_high = signals[signals['zscore'] > 1.8][['zscore', 'beta', 'btc_price', 'eth_price']].tail(5)
extreme_low = signals[signals['zscore'] < -1.8][['zscore', 'beta', 'btc_price', 'eth_price']].tail(5)

if not extreme_high.empty:
    print("\nNear SHORT threshold (z > 1.8):")
    print(extreme_high)

if not extreme_low.empty:
    print("\nNear LONG threshold (z < -1.8):")
    print(extreme_low)

# Recommendation
print()
print("="*60)
print("RECOMMENDATION:")
if long_signals.sum() + short_signals.sum() == 0:
    print("❌ No signals generated with current thresholds (±2.0)")
    print("   Consider:")
    print("   - Lowering entry threshold to ±1.5 or ±1.75")
    print("   - Using more volatile pairs")
    print("   - Increasing data history")
else:
    print(f"✅ {long_signals.sum() + short_signals.sum()} signals generated")
print("="*60)