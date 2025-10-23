#!/usr/bin/env python3
"""Multi-pair scanner for statistical arbitrage opportunities."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.data.cache import DataCache
from src.data.exchange import ExchangeClient
from src.features.spread import SpreadCalculator
from src.utils.config import get_config
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Tuple


def get_signal_status(z_score: float) -> Tuple[str, str]:
    """Determine signal status based on z-score."""
    if pd.isna(z_score):
        return "❌", "No data"
    elif z_score < -2.0:
        return "🟢", f"LONG SIGNAL (z={z_score:.2f})"
    elif z_score > 2.0:
        return "🔴", f"SHORT SIGNAL (z={z_score:.2f})"
    elif abs(z_score) < 0.5:
        return "⚪", f"EXIT ZONE (z={z_score:.2f})"
    elif abs(z_score) > 3.5:
        return "⛔", f"STOP LOSS (z={z_score:.2f})"
    elif z_score < -1.5:
        return "🟡", f"Near long (z={z_score:.2f})"
    elif z_score > 1.5:
        return "🟡", f"Near short (z={z_score:.2f})"
    else:
        return "⚫", f"Neutral (z={z_score:.2f})"


def analyze_pair(cache: DataCache, pair_config: dict) -> dict:
    """Analyze a single trading pair."""
    pair_name = pair_config['name']
    asset_y = pair_config['asset_y']
    asset_x = pair_config['asset_x']

    try:
        # Load data
        y_data = cache.load_ohlcv("binance", asset_y, "1h")
        x_data = cache.load_ohlcv("binance", asset_x, "1h")

        if y_data.empty or x_data.empty:
            return {
                'name': pair_name,
                'status': '❌',
                'message': 'No data',
                'z_score': np.nan,
                'beta': np.nan,
                'spread': np.nan
            }

        # Calculate signals
        signals = SpreadCalculator.calculate_all_signals(
            btc_prices=x_data['close'],  # X asset (denominator)
            eth_prices=y_data['close'],  # Y asset (numerator)
            beta_window=200,
            zscore_window=100
        )

        # Get latest values
        latest = signals.iloc[-1]
        z_score = latest['zscore']

        # Get status
        status_icon, status_msg = get_signal_status(z_score)

        return {
            'name': pair_name,
            'assets': f"{asset_y.split('/')[0]}/{asset_x.split('/')[0]}",
            'status': status_icon,
            'message': status_msg,
            'z_score': z_score,
            'beta': latest['beta'],
            'spread': latest['spread'],
            'y_price': latest['eth_price'],  # Note: column names are legacy
            'x_price': latest['btc_price'],
            'spread_std': latest.get('spread_std', np.nan)
        }

    except Exception as e:
        return {
            'name': pair_name,
            'status': '❌',
            'message': f'Error: {str(e)[:30]}',
            'z_score': np.nan,
            'beta': np.nan,
            'spread': np.nan
        }


def update_all_pairs_data(config: dict, cache: DataCache):
    """Update cache for all configured pairs."""
    print("Fetching data for all configured pairs...")

    # Get unique symbols
    all_symbols = set()
    pairs = config.get('pairs', [])

    for pair in pairs:
        if pair.get('enabled', True):
            all_symbols.add(pair['asset_y'])
            all_symbols.add(pair['asset_x'])

    # Also include legacy symbols
    legacy_symbols = config.get('symbols', {}).get('base', [])
    all_symbols.update(legacy_symbols)

    print(f"Updating {len(all_symbols)} unique symbols...")

    # Update cache for all symbols
    exchange = ExchangeClient()
    for symbol in sorted(all_symbols):
        try:
            print(f"  Fetching {symbol}...", end=" ")
            data = cache.update_cache(
                exchange,
                [symbol],
                config.get('timeframe', '1h'),
                lookback_bars=500
            )
            print(f"✓ ({len(data[symbol])} bars)" if symbol in data else "✗")
        except Exception as e:
            print(f"✗ ({str(e)[:30]})")

    print("Data update complete!")


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description='Multi-pair statistical arbitrage scanner')
    parser.add_argument('--update', action='store_true', help='Update cache for all pairs')
    parser.add_argument('--sort', choices=['zscore', 'name', 'status'], default='zscore',
                       help='Sort results by field')
    args = parser.parse_args()

    # Load config
    config = get_config()
    cache = DataCache()

    # Update cache if requested
    if args.update:
        update_all_pairs_data(config, cache)
        print()

    # Analyze all pairs
    pairs = config.get('pairs', [])
    if not pairs:
        print("No pairs configured in config.yaml")
        return

    results = []
    print("Analyzing configured pairs...")
    for pair_config in pairs:
        if pair_config.get('enabled', True):
            print(f"  Analyzing {pair_config['name']}...", end=" ")
            result = analyze_pair(cache, pair_config)
            results.append(result)
            print(result['status'])

    # Sort results
    if args.sort == 'zscore':
        # Sort by absolute z-score (highest first)
        results.sort(key=lambda x: abs(x['z_score']) if not pd.isna(x['z_score']) else -1, reverse=True)
    elif args.sort == 'status':
        # Sort by signal priority
        priority = {'🔴': 0, '🟢': 1, '🟡': 2, '⚪': 3, '⛔': 4, '⚫': 5, '❌': 6}
        results.sort(key=lambda x: priority.get(x['status'], 7))
    else:  # name
        results.sort(key=lambda x: x['name'])

    # Display results
    print("\n" + "="*80)
    print("MULTI-PAIR STATISTICAL ARBITRAGE SCANNER")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Show active signals first
    active_signals = [r for r in results if r['status'] in ['🔴', '🟢']]
    if active_signals:
        print("\n🚨 ACTIVE SIGNALS:")
        for result in active_signals:
            print(f"  {result['status']} {result['name']:12s} {result['message']}")

    # Show approaching signals
    approaching = [r for r in results if r['status'] == '🟡']
    if approaching:
        print("\n⚠️  APPROACHING SIGNALS:")
        for result in approaching:
            print(f"  {result['status']} {result['name']:12s} {result['message']}")

    # Full table
    print("\nFULL SCAN RESULTS:")
    print("-"*80)
    print(f"{'Status':<6} {'Pair':<12} {'Z-Score':>8} {'Beta':>8} {'Spread':>10} {'Message':<30}")
    print("-"*80)

    for result in results:
        z_str = f"{result['z_score']:8.3f}" if not pd.isna(result['z_score']) else "     N/A"
        beta_str = f"{result['beta']:8.3f}" if not pd.isna(result['beta']) else "     N/A"
        spread_str = f"{result['spread']:10.4f}" if not pd.isna(result['spread']) else "       N/A"

        print(f"{result['status']:<6} {result['name']:<12} {z_str} {beta_str} {spread_str} {result['message']:<30}")

    print("-"*80)

    # Summary statistics
    valid_zscores = [r['z_score'] for r in results if not pd.isna(r['z_score'])]
    if valid_zscores:
        print(f"\nSUMMARY:")
        print(f"  Total pairs scanned: {len(results)}")
        print(f"  Active signals: {len(active_signals)}")
        print(f"  Approaching signals: {len(approaching)}")
        print(f"  Average |Z-score|: {np.mean([abs(z) for z in valid_zscores]):.2f}")
        print(f"  Max |Z-score|: {max([abs(z) for z in valid_zscores]):.2f}")

    print("="*80)


if __name__ == "__main__":
    main()