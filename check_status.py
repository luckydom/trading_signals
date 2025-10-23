#!/usr/bin/env python3
"""Quick status check of current market conditions."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
from src.strategy.state import TradingStateMachine
import pandas as pd

# Load latest data
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

# Get latest values
latest = signals.iloc[-1]
print("="*60)
print("CURRENT MARKET STATUS")
print("="*60)
print(f"Timestamp: {signals.index[-1]}")
print(f"BTC Price: ${latest['btc_price']:,.2f}")
print(f"ETH Price: ${latest['eth_price']:,.2f}")
print(f"Beta (Hedge Ratio): {latest['beta']:.3f}")
print(f"Spread: {latest['spread']:.4f}")
print(f"Z-Score: {latest['zscore']:.3f}")
print()

# Check state
state = TradingStateMachine(z_in=2.0, z_out=0.5, z_stop=3.5)
position = state.get_position_info()
print(f"Current Position: {position['state']}")
print()

# Trading zone analysis
z = latest['zscore']
if pd.notna(z):
    if z < -2.0:
        print("🟢 ENTRY ZONE: Long spread signal (z < -2.0)")
    elif z > 2.0:
        print("🔴 ENTRY ZONE: Short spread signal (z > 2.0)")
    elif abs(z) < 0.5:
        print("⚪ EXIT ZONE: Close position signal (|z| < 0.5)")
    elif abs(z) > 3.5:
        print("⛔ STOP LOSS ZONE: Emergency exit (|z| > 3.5)")
    elif z < -1.5:
        print("🟡 APPROACHING: Near long entry (z = {:.2f})".format(z))
    elif z > 1.5:
        print("🟡 APPROACHING: Near short entry (z = {:.2f})".format(z))
    else:
        print("⚫ NEUTRAL ZONE: No action (z = {:.2f})".format(z))
else:
    print("❌ No valid z-score")

# Historical stats
print()
print("SIGNAL QUALITY (last 500 bars):")
metrics = SpreadCalculator.calculate_signal_quality_metrics(signals)
for key, value in metrics.items():
    if isinstance(value, float):
        print(f"  {key}: {value:.2f}")
    else:
        print(f"  {key}: {value}")

print("="*60)