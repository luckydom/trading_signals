"""Rolling OLS hedge ratio calculation."""

import numpy as np
import pandas as pd
from typing import Optional, Tuple
from numba import jit


class HedgeRatioCalculator:
    """Calculate rolling OLS hedge ratio (beta) between two price series."""

    @staticmethod
    @jit(nopython=True)
    def _calculate_rolling_beta_numba(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
        """
        Fast rolling beta calculation using Numba JIT compilation.

        Args:
            x: Independent variable (log prices of X asset)
            y: Dependent variable (log prices of Y asset)
            window: Rolling window size

        Returns:
            Array of rolling betas
        """
        n = len(x)
        betas = np.full(n, np.nan)

        for i in range(window - 1, n):
            x_window = x[i - window + 1:i + 1]
            y_window = y[i - window + 1:i + 1]

            # Skip if any NaN values
            if np.any(np.isnan(x_window)) or np.any(np.isnan(y_window)):
                continue

            # Calculate covariance and variance
            x_mean = np.mean(x_window)
            y_mean = np.mean(y_window)

            cov_xy = np.sum((x_window - x_mean) * (y_window - y_mean)) / (window - 1)
            var_x = np.sum((x_window - x_mean) ** 2) / (window - 1)

            # Calculate beta (avoid division by zero)
            if var_x > 1e-10:
                betas[i] = cov_xy / var_x

        return betas

    @staticmethod
    def rolling_beta(
        logp_x: pd.Series,
        logp_y: pd.Series,
        window: int,
        min_periods: Optional[int] = None
    ) -> pd.Series:
        """
        Calculate rolling OLS beta using numerically stable approach.

        Args:
            logp_x: Log prices of independent variable (e.g., BTC)
            logp_y: Log prices of dependent variable (e.g., ETH)
            window: Rolling window size
            min_periods: Minimum observations required (default: window)

        Returns:
            Series of rolling beta values
        """
        if min_periods is None:
            min_periods = window

        # Ensure aligned indices
        aligned = pd.DataFrame({'x': logp_x, 'y': logp_y}).dropna()

        if len(aligned) < min_periods:
            return pd.Series(index=aligned.index, dtype=float)

        # Use Numba-optimized calculation
        betas = HedgeRatioCalculator._calculate_rolling_beta_numba(
            aligned['x'].values,
            aligned['y'].values,
            window
        )

        return pd.Series(betas, index=aligned.index, name='beta')

    @staticmethod
    def rolling_beta_stats(
        logp_x: pd.Series,
        logp_y: pd.Series,
        window: int
    ) -> pd.DataFrame:
        """
        Calculate rolling beta with additional statistics.

        Args:
            logp_x: Log prices of independent variable
            logp_y: Log prices of dependent variable
            window: Rolling window size

        Returns:
            DataFrame with beta, R-squared, and residual std
        """
        # Align data
        aligned = pd.DataFrame({'x': logp_x, 'y': logp_y}).dropna()

        if len(aligned) < window:
            return pd.DataFrame(index=aligned.index)

        results = []

        for i in range(window - 1, len(aligned)):
            window_data = aligned.iloc[i - window + 1:i + 1]

            x = window_data['x'].values
            y = window_data['y'].values

            # Calculate statistics
            x_mean = np.mean(x)
            y_mean = np.mean(y)

            # Covariance and variances
            cov_xy = np.cov(x, y)[0, 1]
            var_x = np.var(x, ddof=1)
            var_y = np.var(y, ddof=1)

            if var_x > 1e-10:
                beta = cov_xy / var_x
                alpha = y_mean - beta * x_mean

                # Predicted values and residuals
                y_pred = alpha + beta * x
                residuals = y - y_pred

                # R-squared
                ss_res = np.sum(residuals ** 2)
                ss_tot = np.sum((y - y_mean) ** 2)
                r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

                # Residual standard deviation
                resid_std = np.std(residuals, ddof=2)
            else:
                beta = np.nan
                alpha = np.nan
                r_squared = np.nan
                resid_std = np.nan

            results.append({
                'beta': beta,
                'alpha': alpha,
                'r_squared': r_squared,
                'resid_std': resid_std
            })

        # Create DataFrame with proper index
        results_df = pd.DataFrame(results)
        results_df.index = aligned.index[window - 1:]

        # Reindex to original index and forward fill initial NaNs
        results_df = results_df.reindex(aligned.index)

        return results_df

    @staticmethod
    def calculate_hedge_ratio(
        btc_prices: pd.Series,
        eth_prices: pd.Series,
        window: int = 200,
        use_log: bool = True
    ) -> pd.Series:
        """
        Calculate hedge ratio between BTC and ETH.

        Args:
            btc_prices: BTC price series
            eth_prices: ETH price series
            window: Rolling window for beta calculation
            use_log: Use log prices (recommended for cointegration)

        Returns:
            Series of hedge ratios (beta values)
        """
        # Convert to log prices if requested
        if use_log:
            logp_btc = np.log(btc_prices)
            logp_eth = np.log(eth_prices)
        else:
            logp_btc = btc_prices
            logp_eth = eth_prices

        # Calculate rolling beta (ETH as dependent, BTC as independent)
        return HedgeRatioCalculator.rolling_beta(logp_btc, logp_eth, window)

    @staticmethod
    def validate_cointegration(
        logp_x: pd.Series,
        logp_y: pd.Series,
        beta: float
    ) -> dict:
        """
        Validate cointegration relationship.

        Args:
            logp_x: Log prices of X asset
            logp_y: Log prices of Y asset
            beta: Hedge ratio to test

        Returns:
            Dictionary with validation metrics
        """
        # Calculate spread
        spread = logp_y - beta * logp_x

        # Check stationarity of spread (simple tests)
        spread_mean = spread.mean()
        spread_std = spread.std()

        # Mean reversion tendency
        spread_changes = spread.diff().dropna()
        mean_reversion = -np.corrcoef(spread[:-1], spread_changes)[0, 1]

        # Half-life of mean reversion
        if mean_reversion > 0:
            half_life = -np.log(2) / np.log(1 - mean_reversion)
        else:
            half_life = np.inf

        return {
            'spread_mean': spread_mean,
            'spread_std': spread_std,
            'mean_reversion': mean_reversion,
            'half_life': half_life,
            'is_stationary': mean_reversion > 0.1  # Simple threshold
        }