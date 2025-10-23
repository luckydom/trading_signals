"""Spread and z-score calculations for pairs trading."""

import numpy as np
import pandas as pd
from typing import Optional, Tuple


class SpreadCalculator:
    """Calculate spread and z-score for pairs trading."""

    @staticmethod
    def calculate_spread(
        logp_y: pd.Series,
        logp_x: pd.Series,
        beta: pd.Series
    ) -> pd.Series:
        """
        Calculate the spread between two assets.

        Args:
            logp_y: Log prices of Y asset (e.g., ETH)
            logp_x: Log prices of X asset (e.g., BTC)
            beta: Series of hedge ratios

        Returns:
            Spread series: S_t = log(Y) - beta * log(X)
        """
        # Align all series
        aligned = pd.DataFrame({
            'logp_y': logp_y,
            'logp_x': logp_x,
            'beta': beta
        }).dropna()

        # Calculate spread
        spread = aligned['logp_y'] - aligned['beta'] * aligned['logp_x']
        spread.name = 'spread'

        return spread

    @staticmethod
    def calculate_zscore(
        spread: pd.Series,
        window: int,
        min_periods: Optional[int] = None
    ) -> pd.Series:
        """
        Calculate z-score of the spread.

        Args:
            spread: Spread series
            window: Rolling window for mean/std calculation
            min_periods: Minimum observations required

        Returns:
            Z-score series
        """
        if min_periods is None:
            min_periods = window

        # Rolling statistics
        rolling_mean = spread.rolling(window=window, min_periods=min_periods).mean()
        rolling_std = spread.rolling(window=window, min_periods=min_periods).std()

        # Calculate z-score
        zscore = (spread - rolling_mean) / rolling_std

        # Handle division by zero
        zscore = zscore.replace([np.inf, -np.inf], np.nan)
        zscore.name = 'zscore'

        return zscore

    @staticmethod
    def calculate_all_signals(
        btc_prices: pd.Series,
        eth_prices: pd.Series,
        beta_window: int = 200,
        zscore_window: int = 100
    ) -> pd.DataFrame:
        """
        Calculate all signals: beta, spread, z-score.

        Args:
            btc_prices: BTC price series
            eth_prices: ETH price series
            beta_window: Window for beta calculation
            zscore_window: Window for z-score calculation

        Returns:
            DataFrame with all calculated signals
        """
        # Import beta calculator
        from src.features.beta import HedgeRatioCalculator

        # Calculate log prices
        logp_btc = np.log(btc_prices)
        logp_eth = np.log(eth_prices)

        # Calculate beta
        beta = HedgeRatioCalculator.rolling_beta(logp_btc, logp_eth, beta_window)

        # Calculate spread
        spread = SpreadCalculator.calculate_spread(logp_eth, logp_btc, beta)

        # Calculate z-score
        zscore = SpreadCalculator.calculate_zscore(spread, zscore_window)

        # Combine all signals
        signals = pd.DataFrame({
            'btc_price': btc_prices,
            'eth_price': eth_prices,
            'logp_btc': logp_btc,
            'logp_eth': logp_eth,
            'beta': beta,
            'spread': spread,
            'zscore': zscore
        })

        # Add spread statistics
        signals['spread_mean'] = spread.rolling(window=zscore_window).mean()
        signals['spread_std'] = spread.rolling(window=zscore_window).std()

        return signals

    @staticmethod
    def calculate_spread_half_life(spread: pd.Series) -> float:
        """
        Calculate half-life of mean reversion for the spread.

        Args:
            spread: Spread series

        Returns:
            Half-life in periods
        """
        # Calculate lagged spread
        spread_lag = spread.shift(1)

        # Calculate spread changes
        spread_diff = spread - spread_lag

        # Align data
        aligned = pd.DataFrame({
            'spread_lag': spread_lag,
            'spread_diff': spread_diff
        }).dropna()

        if len(aligned) < 2:
            return np.nan

        # OLS regression: spread_diff = lambda * spread_lag
        # lambda is the mean reversion speed
        x = aligned['spread_lag'].values
        y = aligned['spread_diff'].values

        # Calculate lambda (mean reversion coefficient)
        lambda_coef = np.cov(x, y)[0, 1] / np.var(x)

        # Calculate half-life
        if lambda_coef < 0:
            half_life = -np.log(2) / lambda_coef
        else:
            half_life = np.inf

        return half_life

    @staticmethod
    def identify_outliers(
        zscore: pd.Series,
        threshold: float = 4.0
    ) -> pd.Series:
        """
        Identify outlier points in z-score.

        Args:
            zscore: Z-score series
            threshold: Outlier threshold

        Returns:
            Boolean series indicating outliers
        """
        return np.abs(zscore) > threshold

    @staticmethod
    def calculate_rolling_correlation(
        btc_returns: pd.Series,
        eth_returns: pd.Series,
        window: int = 100
    ) -> pd.Series:
        """
        Calculate rolling correlation between returns.

        Args:
            btc_returns: BTC returns series
            eth_returns: ETH returns series
            window: Rolling window

        Returns:
            Rolling correlation series
        """
        return btc_returns.rolling(window=window).corr(eth_returns)

    @staticmethod
    def calculate_signal_quality_metrics(
        signals: pd.DataFrame,
        lookback: int = 500
    ) -> dict:
        """
        Calculate quality metrics for the trading signals.

        Args:
            signals: DataFrame with calculated signals
            lookback: Number of bars to analyze

        Returns:
            Dictionary with quality metrics
        """
        # Use recent data
        recent = signals.tail(lookback).copy()

        # Remove NaN values for calculations
        clean_zscore = recent['zscore'].dropna()
        clean_spread = recent['spread'].dropna()

        if len(clean_zscore) < 10:
            return {
                'mean_zscore': np.nan,
                'std_zscore': np.nan,
                'spread_half_life': np.nan,
                'zero_crossings': 0,
                'outlier_pct': 0.0,
                'beta_stability': np.nan
            }

        # Calculate metrics (ensure all values are JSON serializable)
        metrics = {
            'mean_zscore': float(clean_zscore.mean()),
            'std_zscore': float(clean_zscore.std()),
            'spread_half_life': float(SpreadCalculator.calculate_spread_half_life(clean_spread)),
            'zero_crossings': int(np.sum(np.diff(np.sign(clean_zscore)) != 0)),
            'outlier_pct': float(np.mean(np.abs(clean_zscore) > 3) * 100),
            'beta_stability': float(recent['beta'].std()) if 'beta' in recent else np.nan
        }

        return metrics