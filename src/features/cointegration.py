"""Cointegration testing for pairs trading."""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict, Any
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.regression.linear_model import OLS
import warnings
warnings.filterwarnings('ignore')


class CointegrationTester:
    """Test and validate cointegration between asset pairs."""

    def __init__(
        self,
        adf_threshold: float = 0.05,
        min_half_life: float = 1.0,
        max_half_life: float = 30.0,
        lookback_window: int = 500
    ):
        """
        Initialize cointegration tester.

        Args:
            adf_threshold: P-value threshold for ADF test (default 0.05 = 95% confidence)
            min_half_life: Minimum acceptable half-life in periods
            max_half_life: Maximum acceptable half-life in periods
            lookback_window: Number of bars to use for testing
        """
        self.adf_threshold = adf_threshold
        self.min_half_life = min_half_life
        self.max_half_life = max_half_life
        self.lookback_window = lookback_window

    def test_cointegration(
        self,
        price1: pd.Series,
        price2: pd.Series
    ) -> Dict[str, Any]:
        """
        Comprehensive cointegration test between two price series.

        Tests include:
        1. Engle-Granger cointegration test
        2. ADF test on the spread
        3. Half-life calculation
        4. Hurst exponent (mean reversion strength)

        Args:
            price1: First asset prices
            price2: Second asset prices

        Returns:
            Dictionary with test results and statistics
        """
        # Ensure we have enough data
        if len(price1) < self.lookback_window or len(price2) < self.lookback_window:
            return {
                'is_cointegrated': False,
                'reason': 'Insufficient data',
                'p_value': 1.0,
                'half_life': None,
                'hedge_ratio': None
            }

        # Use recent data for testing
        p1 = price1.iloc[-self.lookback_window:].values
        p2 = price2.iloc[-self.lookback_window:].values

        # Remove any NaN values
        mask = ~(np.isnan(p1) | np.isnan(p2))
        p1 = p1[mask]
        p2 = p2[mask]

        if len(p1) < 100:  # Need minimum data
            return {
                'is_cointegrated': False,
                'reason': 'Too many NaN values',
                'p_value': 1.0,
                'half_life': None,
                'hedge_ratio': None
            }

        try:
            # 1. Engle-Granger cointegration test
            coint_result = coint(p1, p2)
            eg_pvalue = coint_result[1]

            # 2. Calculate hedge ratio using OLS
            model = OLS(p1, np.column_stack([np.ones(len(p2)), p2]))
            results = model.fit()
            hedge_ratio = results.params[1]
            intercept = results.params[0]

            # 3. Create spread and test stationarity
            spread = p1 - hedge_ratio * p2

            # ADF test on spread
            adf_result = adfuller(spread, autolag='AIC')
            adf_statistic = adf_result[0]
            adf_pvalue = adf_result[1]

            # 4. Calculate half-life of mean reversion
            half_life = self._calculate_half_life(spread)

            # 5. Calculate Hurst exponent (optional - indicates mean reversion strength)
            hurst = self._calculate_hurst_exponent(spread)

            # Determine if pair is tradeable
            is_cointegrated = (
                adf_pvalue < self.adf_threshold and
                eg_pvalue < self.adf_threshold and
                half_life is not None and
                self.min_half_life <= half_life <= self.max_half_life
            )

            reason = self._get_rejection_reason(
                adf_pvalue, eg_pvalue, half_life
            )

            return {
                'is_cointegrated': is_cointegrated,
                'reason': reason if not is_cointegrated else 'Passed all tests',
                'adf_pvalue': adf_pvalue,
                'adf_statistic': adf_statistic,
                'eg_pvalue': eg_pvalue,
                'half_life': half_life,
                'hedge_ratio': hedge_ratio,
                'intercept': intercept,
                'hurst': hurst,
                'spread_mean': np.mean(spread),
                'spread_std': np.std(spread),
                'current_spread': spread[-1] if len(spread) > 0 else None
            }

        except Exception as e:
            return {
                'is_cointegrated': False,
                'reason': f'Test failed: {str(e)}',
                'p_value': 1.0,
                'half_life': None,
                'hedge_ratio': None
            }

    def _calculate_half_life(self, spread: np.ndarray) -> Optional[float]:
        """
        Calculate half-life of mean reversion using Ornstein-Uhlenbeck process.

        The spread follows: dS = -θ(S - μ)dt + σdW
        Half-life = ln(2) / θ
        """
        try:
            # Lag the spread
            spread_lag = np.roll(spread, 1)
            spread_diff = spread - spread_lag

            # Remove first element (no lag for it)
            spread_lag = spread_lag[1:]
            spread_diff = spread_diff[1:]
            spread_mean = np.mean(spread)

            # Regression: spread_diff = -theta * (spread_lag - mean) + noise
            X = spread_lag - spread_mean
            X = X.reshape(-1, 1)

            model = OLS(spread_diff, X)
            results = model.fit()

            theta = -results.params[0]

            if theta <= 0:
                return None  # Not mean reverting

            half_life = np.log(2) / theta
            return half_life

        except:
            return None

    def _calculate_hurst_exponent(self, series: np.ndarray) -> Optional[float]:
        """
        Calculate Hurst exponent.
        H < 0.5: Mean reverting (good for pairs trading)
        H = 0.5: Random walk
        H > 0.5: Trending
        """
        try:
            # Simplified R/S analysis
            lags = range(2, min(100, len(series) // 2))
            tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags]

            # Fit power law
            reg = np.polyfit(np.log(lags), np.log(tau), 1)
            hurst = reg[0]

            return hurst

        except:
            return None

    def _get_rejection_reason(
        self,
        adf_pvalue: float,
        eg_pvalue: float,
        half_life: Optional[float]
    ) -> str:
        """Get human-readable reason for rejection."""
        reasons = []

        if adf_pvalue >= self.adf_threshold:
            reasons.append(f"ADF p-value too high ({adf_pvalue:.3f} >= {self.adf_threshold})")

        if eg_pvalue >= self.adf_threshold:
            reasons.append(f"Engle-Granger p-value too high ({eg_pvalue:.3f} >= {self.adf_threshold})")

        if half_life is None:
            reasons.append("Could not calculate half-life")
        elif half_life < self.min_half_life:
            reasons.append(f"Half-life too short ({half_life:.1f} < {self.min_half_life})")
        elif half_life > self.max_half_life:
            reasons.append(f"Half-life too long ({half_life:.1f} > {self.max_half_life})")

        return "; ".join(reasons) if reasons else "Unknown"

    def test_multiple_pairs(
        self,
        price_data: Dict[str, pd.DataFrame],
        pairs: list
    ) -> Dict[str, Dict[str, Any]]:
        """
        Test cointegration for multiple pairs.

        Args:
            price_data: Dictionary of symbol to price DataFrame
            pairs: List of tuples (symbol1, symbol2)

        Returns:
            Dictionary mapping pair names to test results
        """
        results = {}

        for symbol1, symbol2 in pairs:
            pair_name = f"{symbol1}-{symbol2}"

            if symbol1 not in price_data or symbol2 not in price_data:
                results[pair_name] = {
                    'is_cointegrated': False,
                    'reason': 'Missing price data'
                }
                continue

            df1 = price_data[symbol1]
            df2 = price_data[symbol2]

            # Use close prices
            price1 = df1['close'] if 'close' in df1.columns else df1.iloc[:, 0]
            price2 = df2['close'] if 'close' in df2.columns else df2.iloc[:, 0]

            results[pair_name] = self.test_cointegration(price1, price2)

        return results