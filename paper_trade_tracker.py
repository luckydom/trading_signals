#!/usr/bin/env python3
"""Track paper trading positions and P&L."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import json
from datetime import datetime
import pandas as pd


class PaperTradeTracker:
    """Track paper trading positions."""

    def __init__(self, positions_file="paper_positions.json"):
        self.positions_file = positions_file
        self.positions = self.load_positions()

    def load_positions(self):
        """Load existing positions."""
        if Path(self.positions_file).exists():
            with open(self.positions_file, 'r') as f:
                return json.load(f)
        return {"positions": [], "closed_trades": []}

    def save_positions(self):
        """Save positions to file."""
        with open(self.positions_file, 'w') as f:
            json.dump(self.positions, f, indent=2)

    def open_position(self, pair_name, signal_type, z_score, beta, asset_y_price, asset_x_price, notional=10000):
        """Open a new paper position."""
        position = {
            "id": len(self.positions["positions"]) + len(self.positions["closed_trades"]) + 1,
            "pair": pair_name,
            "signal": signal_type,  # "LONG" or "SHORT"
            "entry_time": datetime.now().isoformat(),
            "entry_z_score": z_score,
            "entry_beta": beta,
            "entry_y_price": asset_y_price,
            "entry_x_price": asset_x_price,
            "notional_usd": notional,
            "status": "OPEN",
            # Calculate position sizes
            "y_position": notional / asset_y_price * (1 if signal_type == "LONG" else -1),
            "x_position": notional * beta / asset_x_price * (-1 if signal_type == "LONG" else 1)
        }

        self.positions["positions"].append(position)
        self.save_positions()

        print(f"\n{'='*60}")
        print(f"PAPER POSITION OPENED")
        print(f"{'='*60}")
        print(f"Pair: {pair_name}")
        print(f"Signal: {signal_type} SPREAD")
        print(f"Z-score: {z_score:.3f}")
        print(f"Beta: {beta:.3f}")
        print(f"Notional: ${notional:,.2f}")
        if signal_type == "SHORT":
            print(f"  Short {abs(position['y_position']):.4f} {pair_name.split('-')[0]} @ ${asset_y_price:.2f}")
            print(f"  Long {abs(position['x_position']):.4f} {pair_name.split('-')[1]} @ ${asset_x_price:.2f}")
        else:
            print(f"  Long {abs(position['y_position']):.4f} {pair_name.split('-')[0]} @ ${asset_y_price:.2f}")
            print(f"  Short {abs(position['x_position']):.4f} {pair_name.split('-')[1]} @ ${asset_x_price:.2f}")
        print(f"{'='*60}")

        return position

    def close_position(self, position_id, current_z_score, current_y_price, current_x_price, reason="TARGET"):
        """Close a paper position."""
        position = None
        for i, p in enumerate(self.positions["positions"]):
            if p["id"] == position_id:
                position = p
                self.positions["positions"].pop(i)
                break

        if not position:
            print(f"Position {position_id} not found")
            return

        # Calculate P&L
        y_pnl = position["y_position"] * (current_y_price - position["entry_y_price"])
        x_pnl = position["x_position"] * (current_x_price - position["entry_x_price"])
        total_pnl = y_pnl + x_pnl

        # Add closing info
        position["exit_time"] = datetime.now().isoformat()
        position["exit_z_score"] = current_z_score
        position["exit_y_price"] = current_y_price
        position["exit_x_price"] = current_x_price
        position["exit_reason"] = reason
        position["pnl_usd"] = total_pnl
        position["return_pct"] = (total_pnl / position["notional_usd"]) * 100
        position["status"] = "CLOSED"

        # Move to closed trades
        self.positions["closed_trades"].append(position)
        self.save_positions()

        print(f"\n{'='*60}")
        print(f"PAPER POSITION CLOSED")
        print(f"{'='*60}")
        print(f"Pair: {position['pair']}")
        print(f"Exit Reason: {reason}")
        print(f"Entry Z-score: {position['entry_z_score']:.3f} → Exit Z-score: {current_z_score:.3f}")
        print(f"P&L: ${total_pnl:,.2f} ({position['return_pct']:.2f}%)")
        print(f"{'='*60}")

        return position

    def show_positions(self):
        """Display all open positions."""
        if not self.positions["positions"]:
            print("No open positions")
            return

        print(f"\n{'='*60}")
        print("OPEN PAPER POSITIONS")
        print(f"{'='*60}")

        for p in self.positions["positions"]:
            duration = (datetime.now() - datetime.fromisoformat(p["entry_time"])).total_seconds() / 3600
            print(f"\nID: {p['id']} | {p['pair']} | {p['signal']} SPREAD")
            print(f"  Entry: Z={p['entry_z_score']:.3f}, Beta={p['entry_beta']:.3f}")
            print(f"  Notional: ${p['notional_usd']:,.2f}")
            print(f"  Duration: {duration:.1f} hours")

        print(f"{'='*60}")

    def show_history(self):
        """Show closed trades history."""
        if not self.positions["closed_trades"]:
            print("No closed trades")
            return

        trades = self.positions["closed_trades"]
        total_pnl = sum(t["pnl_usd"] for t in trades)
        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] <= 0]

        print(f"\n{'='*60}")
        print("PAPER TRADING HISTORY")
        print(f"{'='*60}")
        print(f"Total Trades: {len(trades)}")
        print(f"Wins: {len(wins)} | Losses: {len(losses)}")
        print(f"Win Rate: {len(wins)/len(trades)*100:.1f}%" if trades else "N/A")
        print(f"Total P&L: ${total_pnl:,.2f}")

        print("\nRecent Trades:")
        for t in trades[-5:]:  # Show last 5
            print(f"  {t['pair']}: ${t['pnl_usd']:,.2f} ({t['return_pct']:.2f}%) - {t['exit_reason']}")

        print(f"{'='*60}")


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description='Paper trade tracker')
    parser.add_argument('command', choices=['open', 'close', 'show', 'history'],
                       help='Command to execute')
    parser.add_argument('--pair', help='Pair name (e.g., SOL-ETH)')
    parser.add_argument('--signal', choices=['LONG', 'SHORT'], help='Signal type')
    parser.add_argument('--id', type=int, help='Position ID to close')
    parser.add_argument('--reason', default='TARGET', help='Close reason')
    args = parser.parse_args()

    tracker = PaperTradeTracker()

    if args.command == 'show':
        tracker.show_positions()
    elif args.command == 'history':
        tracker.show_history()
    elif args.command == 'open':
        # Would need to fetch current prices and z-score
        print("Use multi_pair_scanner.py to open positions based on signals")
    elif args.command == 'close':
        if args.id:
            # Would need to fetch current prices
            print(f"To close position {args.id}, run scanner to get current prices")
        else:
            print("Specify position ID with --id")


if __name__ == "__main__":
    main()