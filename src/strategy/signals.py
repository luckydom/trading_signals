"""Enhanced signal generation with cointegration validation."""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, Any
from src.features.beta import BetaCalculator
from src.features.cointegration import CointegrationTester
from src.strategy.state import StateManager
from datetime import datetime


class SignalGenerator:
    """Generate trading signals with cointegration validation."""

    def __init__(self, config: dict):
        """Initialize signal generator with configuration."""
        self.config = config

        # Signal parameters
        self.entry_threshold = config.get('entry_threshold', 2.0)
        self.exit_threshold = config.get('exit_threshold', 0.5)
        self.stop_loss_threshold = config.get('stop_loss_threshold', 3.5)
        self.lookback = config.get('lookback', 60)

        # Initialize components
        self.beta_calculator = BetaCalculator(window=self.lookback)
        self.cointegration_tester = CointegrationTester(
            adf_threshold=config.get('adf_threshold', 0.05),
            min_half_life=config.get('min_half_life', 1.0),
            max_half_life=config.get('max_half_life', 30.0),
            lookback_window=config.get('cointegration_lookback', 500)
        )
        self.state_manager = StateManager(
            entry_threshold=self.entry_threshold,
            exit_threshold=self.exit_threshold,
            stop_loss_threshold=self.stop_loss_threshold
        )

    def generate_signal(
        self,
        df1: pd.DataFrame,
        df2: pd.DataFrame,
        symbol1: str,
        symbol2: str,
        require_cointegration: bool = True
    ) -> Dict[str, Any]:
        """
        Generate trading signal for a pair with cointegration validation.

        Args:
            df1: DataFrame for first asset
            df2: DataFrame for second asset
            symbol1: First symbol name
            symbol2: Second symbol name
            require_cointegration: Whether to require cointegration test to pass

        Returns:
            Dictionary with signal details including cointegration results
        """
        result = {
            'timestamp': datetime.utcnow().isoformat(),
            'pair': f"{symbol1}/{symbol2}",
            'signal': 0,
            'z_score': np.nan,
            'hedge_ratio': np.nan,
            'is_cointegrated': False,
            'cointegration_details': {},
            'can_trade': False,
            'reason': None
        }

        # Ensure we have enough data
        min_length = min(len(df1), len(df2))
        if min_length < self.lookback + 10:
            result['reason'] = 'Insufficient data for analysis'
            return result

        # Align dataframes
        common_index = df1.index.intersection(df2.index)
        if len(common_index) < self.lookback:
            result['reason'] = 'Insufficient overlapping data'
            return result

        df1_aligned = df1.loc[common_index].copy()
        df2_aligned = df2.loc[common_index].copy()

        # Test cointegration if required
        if require_cointegration:
            coint_result = self.cointegration_tester.test_cointegration(
                df1_aligned['close'],
                df2_aligned['close']
            )
            result['is_cointegrated'] = coint_result['is_cointegrated']
            result['cointegration_details'] = coint_result

            if not coint_result['is_cointegrated']:
                result['reason'] = f"Not cointegrated: {coint_result['reason']}"
                result['can_trade'] = False
                return result

        # Calculate beta (hedge ratio)
        prices1 = df1_aligned['close'].values
        prices2 = df2_aligned['close'].values

        betas = self.beta_calculator.calculate_rolling_beta(prices1, prices2)

        if np.all(np.isnan(betas)):
            result['reason'] = 'Failed to calculate hedge ratio'
            return result

        # Get current beta
        current_beta = betas[-1]
        if np.isnan(current_beta):
            result['reason'] = 'Current hedge ratio is NaN'
            return result

        result['hedge_ratio'] = float(current_beta)

        # Calculate spread and z-score
        spread = prices1 - current_beta * prices2
        spread_mean = np.nanmean(spread[-self.lookback:])
        spread_std = np.nanstd(spread[-self.lookback:])

        if spread_std > 0:
            z_score = (spread[-1] - spread_mean) / spread_std
            result['z_score'] = float(z_score)

            # Generate signal using state manager
            signal = self.state_manager.update(z_score)
            result['signal'] = int(signal)

            # Determine if we can trade
            result['can_trade'] = (
                result['is_cointegrated'] and
                signal != 0
            )

            # Add signal description
            if signal == 1:
                result['signal_type'] = 'LONG'
                result['action'] = f"Long {symbol1}, Short {symbol2}"
            elif signal == -1:
                result['signal_type'] = 'SHORT'
                result['action'] = f"Short {symbol1}, Long {symbol2}"
            else:
                result['signal_type'] = 'NEUTRAL'
                result['action'] = 'No action'

            # Add statistics
            result['spread_mean'] = float(spread_mean)
            result['spread_std'] = float(spread_std)
            result['current_spread'] = float(spread[-1])

            # Add confidence metrics
            if require_cointegration and 'half_life' in coint_result:
                result['half_life'] = coint_result['half_life']
                result['confidence'] = self._calculate_confidence(
                    z_score,
                    coint_result.get('adf_pvalue', 1.0),
                    coint_result.get('half_life')
                )
        else:
            result['reason'] = 'Zero spread standard deviation'

        return result

    def _calculate_confidence(
        self,
        z_score: float,
        p_value: float,
        half_life: Optional[float]
    ) -> float:
        """
        Calculate trading confidence score (0-100).

        Factors:
        - Cointegration strength (p-value)
        - Z-score magnitude
        - Half-life quality
        """
        confidence = 0.0

        # Cointegration strength (up to 40 points)
        if p_value < 0.01:
            confidence += 40
        elif p_value < 0.03:
            confidence += 30
        elif p_value < 0.05:
            confidence += 20

        # Z-score magnitude (up to 40 points)
        abs_z = abs(z_score)
        if abs_z > 3.0:
            confidence += 40
        elif abs_z > 2.5:
            confidence += 30
        elif abs_z > 2.0:
            confidence += 20

        # Half-life quality (up to 20 points)
        if half_life is not None:
            if 2 <= half_life <= 10:
                confidence += 20
            elif 1 <= half_life <= 20:
                confidence += 10

        return confidence

    def scan_all_pairs(
        self,
        price_data: Dict[str, pd.DataFrame],
        pairs: list,
        require_cointegration: bool = True
    ) -> Dict[str, Dict[str, Any]]:
        """
        Scan multiple pairs for signals.

        Args:
            price_data: Dictionary of symbol to DataFrame
            pairs: List of (symbol1, symbol2) tuples
            require_cointegration: Whether to require cointegration

        Returns:
            Dictionary of pair results
        """
        results = {}

        for symbol1, symbol2 in pairs:
            pair_name = f"{symbol1}/{symbol2}"

            if symbol1 not in price_data or symbol2 not in price_data:
                results[pair_name] = {
                    'signal': 0,
                    'can_trade': False,
                    'reason': 'Missing price data'
                }
                continue

            df1 = price_data[symbol1]
            df2 = price_data[symbol2]

            signal_result = self.generate_signal(
                df1, df2, symbol1, symbol2,
                require_cointegration=require_cointegration
            )

            results[pair_name] = signal_result

        return results