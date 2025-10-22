"""Trade ticket generation and formatting."""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

from src.strategy.state import TradingSignal, SignalType
from src.strategy.sizing import PositionSize


class TradeTicketGenerator:
    """Generate human-readable trade tickets."""

    def generate_ticket(
        self,
        signal: TradingSignal,
        position_size: PositionSize,
        funding_info: Optional[Dict] = None
    ) -> str:
        """
        Generate a formatted trade ticket.

        Args:
            signal: Trading signal
            position_size: Position sizing information
            funding_info: Optional funding rate information

        Returns:
            Formatted trade ticket string
        """
        # Format timestamp
        timestamp_str = signal.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Determine action
        if signal.signal_type == SignalType.ENTER_LONG_SPREAD:
            action = "ENTER Long Spread (ETH long / BTC short)"
            eth_side = "LONG"
            btc_side = "SHORT"
        elif signal.signal_type == SignalType.ENTER_SHORT_SPREAD:
            action = "ENTER Short Spread (ETH short / BTC long)"
            eth_side = "SHORT"
            btc_side = "LONG"
        elif signal.signal_type == SignalType.EXIT_POSITION:
            action = "EXIT Position"
            eth_side = "CLOSE"
            btc_side = "CLOSE"
        elif signal.signal_type == SignalType.STOP_LOSS:
            action = "STOP LOSS Triggered"
            eth_side = "CLOSE"
            btc_side = "CLOSE"
        else:
            action = "NO ACTION"
            eth_side = "NONE"
            btc_side = "NONE"

        # Build ticket
        ticket_lines = [
            "=" * 60,
            "TRADE TICKET",
            "=" * 60,
            f"Timestamp: {timestamp_str}",
            f"Signal: {action}",
            "",
            "Market Data:",
            f"  Z-score: {signal.zscore:.3f}",
            f"  Beta (hedge ratio): {signal.beta:.3f}",
            f"  Spread: {signal.spread:.4f}",
            f"  BTC Price: ${signal.btc_price:,.2f}",
            f"  ETH Price: ${signal.eth_price:,.2f}",
            "",
            "Position Details:",
            f"  ETH: {eth_side} ${position_size.eth_notional_usd:,.2f} ({position_size.eth_units:.4f} ETH)",
            f"  BTC: {btc_side} ${position_size.btc_notional_usd:,.2f} ({position_size.btc_units:.6f} BTC)",
            f"  Total Notional: ${position_size.total_notional:,.2f}",
            f"  Leverage: {position_size.leverage:.1f}x",
            "",
            "Risk Parameters:",
            f"  Stop Loss: |z| > 3.5",
            f"  Exit Target: |z| < 0.5",
            f"  Risk per Z-score: ${position_size.risk_per_zscore:.2f}",
            "",
            "Costs:",
            f"  Est. Fees: ${position_size.expected_fees:.2f}",
            f"  Est. Slippage: ${position_size.expected_slippage:.2f}",
            "",
            "Notes:",
            f"  Reason: {signal.reason}",
        ]

        # Add funding info if available
        if funding_info:
            btc_funding = funding_info.get('btc_funding', 0)
            eth_funding = funding_info.get('eth_funding', 0)
            funding_diff = abs(btc_funding - eth_funding)
            ticket_lines.extend([
                f"  BTC Funding: {btc_funding:.4%}",
                f"  ETH Funding: {eth_funding:.4%}",
                f"  Funding Diff: {funding_diff:.4%}",
            ])

        ticket_lines.append("=" * 60)

        return "\n".join(ticket_lines)

    def save_ticket(self, ticket: str, run_id: str) -> Path:
        """
        Save trade ticket to file.

        Args:
            ticket: Formatted ticket string
            run_id: Run identifier

        Returns:
            Path to saved ticket file
        """
        ticket_dir = Path("signals")
        ticket_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ticket_file = ticket_dir / f"ticket_{timestamp}_{run_id}.txt"

        with open(ticket_file, 'w') as f:
            f.write(ticket)

        return ticket_file

    def save_ticket_json(
        self,
        signal: TradingSignal,
        position_size: PositionSize,
        run_id: str
    ) -> Path:
        """
        Save ticket data as JSON for programmatic access.

        Args:
            signal: Trading signal
            position_size: Position sizing information
            run_id: Run identifier

        Returns:
            Path to saved JSON file
        """
        ticket_dir = Path("signals")
        ticket_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_file = ticket_dir / f"signal_{timestamp}_{run_id}.json"

        data = {
            'timestamp': signal.timestamp.isoformat(),
            'signal_type': signal.signal_type.value,
            'zscore': signal.zscore,
            'beta': signal.beta,
            'spread': signal.spread,
            'btc_price': signal.btc_price,
            'eth_price': signal.eth_price,
            'reason': signal.reason,
            'position': {
                'eth_notional_usd': position_size.eth_notional_usd,
                'btc_notional_usd': position_size.btc_notional_usd,
                'eth_units': position_size.eth_units,
                'btc_units': position_size.btc_units,
                'total_notional': position_size.total_notional,
                'leverage': position_size.leverage,
                'expected_fees': position_size.expected_fees,
                'expected_slippage': position_size.expected_slippage,
                'risk_per_zscore': position_size.risk_per_zscore
            }
        }

        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)

        return json_file