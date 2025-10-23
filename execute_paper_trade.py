#!/usr/bin/env python3
"""Execute paper trades based on current signals."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from paper_trade_tracker import PaperTradeTracker
from src.data.cache import DataCache
from src.features.spread import SpreadCalculator
from src.utils.config import get_config
import pandas as pd


def get_current_prices_and_signal(pair_config):
    """Get current prices and z-score for a pair."""
    cache = DataCache()

    # Load data
    y_data = cache.load_ohlcv("binance", pair_config['asset_y'], "1h")
    x_data = cache.load_ohlcv("binance", pair_config['asset_x'], "1h")

    # Calculate signals
    signals = SpreadCalculator.calculate_all_signals(
        btc_prices=x_data['close'],
        eth_prices=y_data['close'],
        beta_window=200,
        zscore_window=100
    )

    latest = signals.iloc[-1]

    return {
        'y_price': latest['eth_price'],
        'x_price': latest['btc_price'],
        'z_score': latest['zscore'],
        'beta': latest['beta'],
        'spread': latest['spread']
    }


def main():
    """Execute paper trades based on current signals."""
    config = get_config()
    tracker = PaperTradeTracker()

    # First, show current positions
    print("\n" + "="*60)
    print("CURRENT POSITIONS CHECK")
    print("="*60)
    tracker.show_positions()

    # Find SOL-ETH pair config
    sol_eth_config = None
    for pair in config.get('pairs', []):
        if pair['name'] == 'SOL-ETH':
            sol_eth_config = pair
            break

    if not sol_eth_config:
        print("SOL-ETH pair not found in config")
        return

    # Get current market data
    print("\nFetching current market data for SOL-ETH...")
    current = get_current_prices_and_signal(sol_eth_config)

    print(f"\nCurrent SOL-ETH Status:")
    print(f"  SOL Price: ${current['y_price']:.2f}")
    print(f"  ETH Price: ${current['x_price']:.2f}")
    print(f"  Z-Score: {current['z_score']:.3f}")
    print(f"  Beta: {current['beta']:.3f}")

    # Check if we should open a position
    if abs(current['z_score']) > 2.0:
        # Determine signal type
        if current['z_score'] > 2.0:
            signal_type = "SHORT"
            print(f"\n🔴 SHORT SIGNAL DETECTED (Z-score = {current['z_score']:.3f})")
        else:
            signal_type = "LONG"
            print(f"\n🟢 LONG SIGNAL DETECTED (Z-score = {current['z_score']:.3f})")

        # Check if we already have an open position for this pair
        existing_position = None
        for pos in tracker.positions.get("positions", []):
            if pos["pair"] == "SOL-ETH" and pos["status"] == "OPEN":
                existing_position = pos
                break

        if existing_position:
            print(f"\n⚠️ Already have an open position for SOL-ETH (ID: {existing_position['id']})")
            print(f"  Entry Z-score: {existing_position['entry_z_score']:.3f}")
            print(f"  Current Z-score: {current['z_score']:.3f}")

            # Calculate current P&L
            y_pnl = existing_position["y_position"] * (current['y_price'] - existing_position["entry_y_price"])
            x_pnl = existing_position["x_position"] * (current['x_price'] - existing_position["entry_x_price"])
            current_pnl = y_pnl + x_pnl
            print(f"  Current P&L: ${current_pnl:,.2f}")

            # Check exit conditions
            if abs(current['z_score']) < 0.5:
                print("\n✅ EXIT CONDITION MET (|Z| < 0.5)")
                tracker.close_position(
                    existing_position['id'],
                    current['z_score'],
                    current['y_price'],
                    current['x_price'],
                    "TARGET"
                )
            elif abs(current['z_score']) > 3.5:
                print("\n⛔ STOP LOSS TRIGGERED (|Z| > 3.5)")
                tracker.close_position(
                    existing_position['id'],
                    current['z_score'],
                    current['y_price'],
                    current['x_price'],
                    "STOP_LOSS"
                )
        else:
            # Open new position
            print(f"\n💼 OPENING PAPER POSITION")
            position = tracker.open_position(
                pair_name="SOL-ETH",
                signal_type=signal_type,
                z_score=current['z_score'],
                beta=current['beta'],
                asset_y_price=current['y_price'],
                asset_x_price=current['x_price'],
                notional=10000  # $10k paper position
            )

            print(f"\n📊 Position Details:")
            print(f"  Position ID: {position['id']}")
            print(f"  Exit Target: |Z-score| < 0.5 (currently {current['z_score']:.3f})")
            print(f"  Stop Loss: |Z-score| > 3.5")

    else:
        print(f"\n⚫ No signal - Z-score {current['z_score']:.3f} is between -2.0 and 2.0")

        # Check if we have positions to close
        for pos in tracker.positions.get("positions", []):
            if pos["pair"] == "SOL-ETH" and pos["status"] == "OPEN":
                print(f"\n📈 Monitoring open position (ID: {pos['id']})")

                # Calculate current P&L
                y_pnl = pos["y_position"] * (current['y_price'] - pos["entry_y_price"])
                x_pnl = pos["x_position"] * (current['x_price'] - pos["entry_x_price"])
                current_pnl = y_pnl + x_pnl

                print(f"  Entry Z-score: {pos['entry_z_score']:.3f}")
                print(f"  Current Z-score: {current['z_score']:.3f}")
                print(f"  Current P&L: ${current_pnl:,.2f}")

                if abs(current['z_score']) < 0.5:
                    print("\n✅ EXIT TARGET REACHED!")
                    tracker.close_position(
                        pos['id'],
                        current['z_score'],
                        current['y_price'],
                        current['x_price'],
                        "TARGET"
                    )

    # Show final status
    print("\n" + "="*60)
    print("PAPER TRADING SUMMARY")
    print("="*60)
    tracker.show_history()


if __name__ == "__main__":
    main()