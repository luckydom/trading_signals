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
        y_symbol: str,
        x_symbol: str,
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

        # Resolve leg labels from symbols (use base asset names)
        y_name = (y_symbol.split("/")[0] if "/" in y_symbol else y_symbol)
        x_name = (x_symbol.split("/")[0] if "/" in x_symbol else x_symbol)

        # Determine action
        if signal.signal_type == SignalType.ENTER_LONG_SPREAD:
            action = f"ENTER Long Spread ({y_name} long / {x_name} short)"
            y_side = "LONG"
            x_side = "SHORT"
        elif signal.signal_type == SignalType.ENTER_SHORT_SPREAD:
            action = f"ENTER Short Spread ({y_name} short / {x_name} long)"
            y_side = "SHORT"
            x_side = "LONG"
        elif signal.signal_type == SignalType.EXIT_POSITION:
            action = "EXIT Position"
            y_side = "CLOSE"
            x_side = "CLOSE"
        elif signal.signal_type == SignalType.STOP_LOSS:
            action = "STOP LOSS Triggered"
            y_side = "CLOSE"
            x_side = "CLOSE"
        else:
            action = "NO ACTION"
            y_side = "NONE"
            x_side = "NONE"

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
            f"  {x_name} Price: ${signal.btc_price:,.2f}",
            f"  {y_name} Price: ${signal.eth_price:,.2f}",
            "",
            "Position Details:",
            f"  {y_name}: {y_side} ${position_size.eth_notional_usd:,.2f} ({position_size.eth_units:.4f} {y_name})",
            f"  {x_name}: {x_side} ${position_size.btc_notional_usd:,.2f} ({position_size.btc_units:.6f} {x_name})",
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
