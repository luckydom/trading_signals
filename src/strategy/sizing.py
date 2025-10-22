"""Position sizing with volatility targeting."""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class PositionSize:
    """Position size for each leg of the trade."""
    eth_notional_usd: float
    btc_notional_usd: float
    eth_units: float
    btc_units: float
    total_notional: float
    leverage: float
    expected_fees: float
    expected_slippage: float
    risk_per_zscore: float


class VolatilityTargetingSizer:
    """
    Position sizing based on volatility targeting.

    The goal is to size positions such that a 1-sigma move in the spread
    results in a target P&L in USD.
    """

    def __init__(
        self,
        target_sigma_usd: float = 200.0,
        max_notional_per_leg: float = 25000.0,
        max_adv_fraction: float = 0.05,
        fee_bps: float = 10.0,
        slippage_bps: float = 5.0,
        min_notional_per_leg: float = 100.0
    ):
        """
        Initialize position sizer.

        Args:
            target_sigma_usd: Target P&L for 1-sigma spread move
            max_notional_per_leg: Maximum notional value per leg
            max_adv_fraction: Maximum fraction of ADV to trade
            fee_bps: Trading fee in basis points
            slippage_bps: Expected slippage in basis points
            min_notional_per_leg: Minimum notional value per leg
        """
        self.target_sigma_usd = target_sigma_usd
        self.max_notional_per_leg = max_notional_per_leg
        self.max_adv_fraction = max_adv_fraction
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.min_notional_per_leg = min_notional_per_leg

    def calculate_position_size(
        self,
        beta: float,
        spread_std: float,
        btc_price: float,
        eth_price: float,
        btc_adv_usd: Optional[float] = None,
        eth_adv_usd: Optional[float] = None,
        capital: Optional[float] = None
    ) -> PositionSize:
        """
        Calculate position size for a pairs trade.

        Args:
            beta: Hedge ratio (ETH/BTC beta)
            spread_std: Standard deviation of the spread
            btc_price: Current BTC price
            eth_price: Current ETH price
            btc_adv_usd: BTC average daily volume in USD
            eth_adv_usd: ETH average daily volume in USD
            capital: Available capital (for leverage calculation)

        Returns:
            PositionSize object with sizing details
        """
        # Calculate base notional to achieve target P&L per sigma
        # For spread S = log(ETH) - beta * log(BTC)
        # A 1-sigma move in spread should result in target_sigma_usd P&L

        # The P&L sensitivity to spread is approximately:
        # P&L ≈ N_ETH * (exp(dS) - 1) ≈ N_ETH * dS for small dS
        # where N_ETH is the ETH notional

        # Therefore: N_ETH = target_sigma_usd / spread_std
        eth_notional_base = self.target_sigma_usd / spread_std if spread_std > 0 else 0

        # Calculate BTC notional to maintain hedge ratio
        # We need: N_BTC / N_ETH ≈ beta * (P_BTC / P_ETH)
        # So: N_BTC = N_ETH * beta * (P_BTC / P_ETH)
        btc_notional_base = eth_notional_base * beta

        # Apply position limits
        eth_notional = min(eth_notional_base, self.max_notional_per_leg)
        btc_notional = min(btc_notional_base, self.max_notional_per_leg)

        # Maintain hedge ratio after limiting
        if eth_notional < eth_notional_base or btc_notional < btc_notional_base:
            # Scale both to maintain ratio
            scale = min(
                self.max_notional_per_leg / eth_notional_base,
                self.max_notional_per_leg / btc_notional_base
            )
            eth_notional = eth_notional_base * scale
            btc_notional = btc_notional_base * scale

        # Apply ADV constraints if provided
        if btc_adv_usd and btc_adv_usd > 0:
            max_btc_notional = btc_adv_usd * self.max_adv_fraction
            if btc_notional > max_btc_notional:
                scale = max_btc_notional / btc_notional
                btc_notional *= scale
                eth_notional *= scale  # Maintain ratio

        if eth_adv_usd and eth_adv_usd > 0:
            max_eth_notional = eth_adv_usd * self.max_adv_fraction
            if eth_notional > max_eth_notional:
                scale = max_eth_notional / eth_notional
                eth_notional *= scale
                btc_notional *= scale  # Maintain ratio

        # Check minimum size
        if eth_notional < self.min_notional_per_leg or btc_notional < self.min_notional_per_leg:
            eth_notional = 0
            btc_notional = 0

        # Calculate units
        eth_units = eth_notional / eth_price if eth_price > 0 else 0
        btc_units = btc_notional / btc_price if btc_price > 0 else 0

        # Calculate total notional and leverage
        total_notional = eth_notional + btc_notional
        leverage = total_notional / capital if capital and capital > 0 else 0

        # Calculate expected costs
        expected_fees = total_notional * (self.fee_bps / 10000)
        expected_slippage = total_notional * (self.slippage_bps / 10000)

        # Calculate actual risk per z-score
        risk_per_zscore = eth_notional * spread_std if spread_std > 0 else 0

        return PositionSize(
            eth_notional_usd=eth_notional,
            btc_notional_usd=btc_notional,
            eth_units=eth_units,
            btc_units=btc_units,
            total_notional=total_notional,
            leverage=leverage,
            expected_fees=expected_fees,
            expected_slippage=expected_slippage,
            risk_per_zscore=risk_per_zscore
        )

    def calculate_kelly_fraction(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        kelly_scale: float = 0.25
    ) -> float:
        """
        Calculate Kelly fraction for position sizing.

        Args:
            win_rate: Historical win rate (0-1)
            avg_win: Average winning trade return
            avg_loss: Average losing trade return (positive value)
            kelly_scale: Scale factor for Kelly (e.g., 0.25 for quarter-Kelly)

        Returns:
            Kelly fraction to use for sizing
        """
        if avg_loss <= 0 or avg_win <= 0:
            return 0

        # Kelly formula: f = (p * b - q) / b
        # where p = win_rate, q = 1-p, b = avg_win/avg_loss
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p

        kelly_full = (p * b - q) / b

        # Apply scaling and limits
        kelly_fraction = max(0, min(kelly_full * kelly_scale, 0.25))

        return kelly_fraction

    def adjust_size_for_volatility_regime(
        self,
        base_size: PositionSize,
        current_vol: float,
        target_vol: float
    ) -> PositionSize:
        """
        Adjust position size based on volatility regime.

        Args:
            base_size: Base position size
            current_vol: Current realized volatility
            target_vol: Target volatility

        Returns:
            Adjusted PositionSize
        """
        if current_vol <= 0 or target_vol <= 0:
            return base_size

        # Scale inversely with volatility
        vol_scalar = min(2.0, max(0.5, target_vol / current_vol))

        return PositionSize(
            eth_notional_usd=base_size.eth_notional_usd * vol_scalar,
            btc_notional_usd=base_size.btc_notional_usd * vol_scalar,
            eth_units=base_size.eth_units * vol_scalar,
            btc_units=base_size.btc_units * vol_scalar,
            total_notional=base_size.total_notional * vol_scalar,
            leverage=base_size.leverage * vol_scalar,
            expected_fees=base_size.expected_fees * vol_scalar,
            expected_slippage=base_size.expected_slippage * vol_scalar,
            risk_per_zscore=base_size.risk_per_zscore * vol_scalar
        )

    @staticmethod
    def calculate_portfolio_risk_metrics(
        positions: Dict[str, PositionSize],
        correlations: pd.DataFrame
    ) -> dict:
        """
        Calculate portfolio-level risk metrics.

        Args:
            positions: Dictionary of position sizes by pair
            correlations: Correlation matrix between pairs

        Returns:
            Portfolio risk metrics
        """
        if not positions:
            return {
                'total_notional': 0,
                'total_risk': 0,
                'concentration_ratio': 0,
                'max_position_pct': 0
            }

        total_notional = sum(p.total_notional for p in positions.values())
        risks = [p.risk_per_zscore for p in positions.values()]

        # Calculate portfolio risk considering correlations
        if len(risks) == 1:
            total_risk = risks[0]
        else:
            # Simple approximation without full correlation matrix
            total_risk = np.sqrt(sum(r**2 for r in risks))

        # Concentration metrics
        notionals = [p.total_notional for p in positions.values()]
        max_notional = max(notionals) if notionals else 0
        concentration_ratio = max_notional / total_notional if total_notional > 0 else 0

        return {
            'total_notional': total_notional,
            'total_risk': total_risk,
            'concentration_ratio': concentration_ratio,
            'max_position_pct': concentration_ratio * 100,
            'n_positions': len(positions)
        }