"""Vectorized backtesting engine for pairs trading strategy."""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta


@dataclass
class BacktestResults:
    """Container for backtest results."""
    equity_curve: pd.Series
    trades: pd.DataFrame
    signals: pd.DataFrame
    metrics: dict
    positions: pd.DataFrame


class VectorizedBacktester:
    """
    Vectorized backtesting engine for pairs trading.

    This backtester simulates trading with next-bar execution,
    accounting for fees and slippage.
    """

    def __init__(
        self,
        initial_capital: float = 100000,
        fee_bps: float = 10.0,
        slippage_bps: float = 5.0,
        target_sigma_usd: float = 200.0,
        max_notional_per_leg: float = 25000.0
    ):
        """
        Initialize backtester.

        Args:
            initial_capital: Starting capital in USD
            fee_bps: Trading fees in basis points
            slippage_bps: Slippage in basis points
            target_sigma_usd: Target P&L per sigma move
            max_notional_per_leg: Maximum position per leg
        """
        self.initial_capital = initial_capital
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.target_sigma_usd = target_sigma_usd
        self.max_notional_per_leg = max_notional_per_leg

    def run_backtest(
        self,
        signals_df: pd.DataFrame,
        z_in: float = 2.0,
        z_out: float = 0.5,
        z_stop: float = 3.5
    ) -> BacktestResults:
        """
        Run vectorized backtest on signals.

        Args:
            signals_df: DataFrame with columns: btc_price, eth_price, beta, zscore, spread_std
            z_in: Entry threshold
            z_out: Exit threshold
            z_stop: Stop loss threshold

        Returns:
            BacktestResults object
        """
        # Ensure required columns exist
        required_cols = ['btc_price', 'eth_price', 'beta', 'zscore']
        for col in required_cols:
            if col not in signals_df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Calculate spread std if not provided
        if 'spread_std' not in signals_df.columns:
            signals_df = signals_df.copy()
            signals_df['spread_std'] = signals_df['spread'].rolling(100).std()

        # Generate entry/exit signals vectorized
        signals = self._generate_signals_vectorized(signals_df, z_in, z_out, z_stop)

        # Calculate positions (with next-bar execution)
        positions = self._calculate_positions(signals)

        # Calculate P&L
        equity_curve, trades = self._calculate_pnl(signals_df, positions)

        # Calculate metrics
        metrics = self._calculate_metrics(equity_curve, trades)

        return BacktestResults(
            equity_curve=equity_curve,
            trades=trades,
            signals=signals,
            metrics=metrics,
            positions=positions
        )

    def _generate_signals_vectorized(
        self,
        df: pd.DataFrame,
        z_in: float,
        z_out: float,
        z_stop: float
    ) -> pd.DataFrame:
        """Generate entry/exit signals using vectorized operations."""
        signals = df.copy()

        # Initialize signal columns
        signals['signal'] = 0
        signals['position'] = 0

        # Entry signals (crossing detection)
        z_prev = signals['zscore'].shift(1)

        # Long entry: z crosses below -z_in
        long_entry = (z_prev >= -z_in) & (signals['zscore'] < -z_in)

        # Short entry: z crosses above z_in
        short_entry = (z_prev <= z_in) & (signals['zscore'] > z_in)

        # Mark entry points
        signals.loc[long_entry, 'signal'] = 1
        signals.loc[short_entry, 'signal'] = -1

        # Forward fill positions
        position = 0
        positions = []

        for i in range(len(signals)):
            if pd.notna(signals.iloc[i]['zscore']):
                # Check for new signal
                if signals.iloc[i]['signal'] != 0:
                    position = signals.iloc[i]['signal']

                # Check for exit conditions if in position
                elif position != 0:
                    z = signals.iloc[i]['zscore']

                    # Exit conditions
                    if abs(z) < z_out or abs(z) > z_stop:
                        position = 0

            positions.append(position)

        signals['position'] = positions

        return signals

    def _calculate_positions(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Calculate actual positions with sizing."""
        positions = signals.copy()

        # Calculate position sizes
        if 'spread_std' in positions.columns:
            # Size based on spread volatility
            positions['eth_notional'] = np.where(
                positions['position'] != 0,
                np.minimum(
                    self.target_sigma_usd / positions['spread_std'].fillna(1),
                    self.max_notional_per_leg
                ),
                0
            )
        else:
            # Fixed sizing
            positions['eth_notional'] = np.where(
                positions['position'] != 0,
                self.max_notional_per_leg,
                0
            )

        # Calculate BTC notional based on hedge ratio
        positions['btc_notional'] = positions['eth_notional'] * positions['beta'].fillna(1)

        # Calculate units
        positions['eth_units'] = positions['eth_notional'] / positions['eth_price']
        positions['btc_units'] = positions['btc_notional'] / positions['btc_price']

        # Adjust for position direction
        # Long spread: Long ETH, Short BTC (position = 1)
        # Short spread: Short ETH, Long BTC (position = -1)
        positions['eth_units'] = positions['eth_units'] * positions['position']
        positions['btc_units'] = positions['btc_units'] * -positions['position']

        return positions

    def _calculate_pnl(
        self,
        signals_df: pd.DataFrame,
        positions: pd.DataFrame
    ) -> Tuple[pd.Series, pd.DataFrame]:
        """Calculate P&L accounting for fees and slippage."""
        pnl = pd.DataFrame(index=positions.index)

        # Calculate returns
        eth_returns = signals_df['eth_price'].pct_change()
        btc_returns = signals_df['btc_price'].pct_change()

        # Position changes for fee calculation
        eth_units_change = positions['eth_units'].diff().fillna(positions['eth_units'])
        btc_units_change = positions['btc_units'].diff().fillna(positions['btc_units'])

        # Trading costs (fees + slippage)
        total_cost_bps = self.fee_bps + self.slippage_bps
        eth_trade_cost = abs(eth_units_change * signals_df['eth_price']) * (total_cost_bps / 10000)
        btc_trade_cost = abs(btc_units_change * signals_df['btc_price']) * (total_cost_bps / 10000)

        # P&L from positions (use previous bar's position with current bar's return)
        eth_pnl = positions['eth_units'].shift(1) * signals_df['eth_price'] * eth_returns
        btc_pnl = positions['btc_units'].shift(1) * signals_df['btc_price'] * btc_returns

        # Total P&L
        pnl['eth_pnl'] = eth_pnl.fillna(0)
        pnl['btc_pnl'] = btc_pnl.fillna(0)
        pnl['trade_costs'] = -(eth_trade_cost + btc_trade_cost)
        pnl['total_pnl'] = pnl['eth_pnl'] + pnl['btc_pnl'] + pnl['trade_costs']

        # Cumulative equity
        equity_curve = self.initial_capital + pnl['total_pnl'].cumsum()

        # Extract trades
        trades = self._extract_trades(positions, pnl)

        return equity_curve, trades

    def _extract_trades(
        self,
        positions: pd.DataFrame,
        pnl: pd.DataFrame
    ) -> pd.DataFrame:
        """Extract individual trades from positions."""
        trades = []
        current_trade = None

        for i in range(1, len(positions)):
            prev_pos = positions.iloc[i-1]['position']
            curr_pos = positions.iloc[i]['position']

            # New trade opened
            if prev_pos == 0 and curr_pos != 0:
                current_trade = {
                    'entry_date': positions.index[i],
                    'entry_price_btc': positions.iloc[i]['btc_price'],
                    'entry_price_eth': positions.iloc[i]['eth_price'],
                    'entry_zscore': positions.iloc[i]['zscore'],
                    'entry_beta': positions.iloc[i]['beta'],
                    'direction': 'long_spread' if curr_pos > 0 else 'short_spread',
                    'pnl': 0
                }

            # Trade closed
            elif prev_pos != 0 and curr_pos == 0 and current_trade:
                current_trade['exit_date'] = positions.index[i]
                current_trade['exit_price_btc'] = positions.iloc[i]['btc_price']
                current_trade['exit_price_eth'] = positions.iloc[i]['eth_price']
                current_trade['exit_zscore'] = positions.iloc[i]['zscore']

                # Calculate trade P&L
                start_idx = positions.index.get_loc(current_trade['entry_date'])
                end_idx = i
                current_trade['pnl'] = pnl['total_pnl'].iloc[start_idx:end_idx+1].sum()

                # Calculate duration
                duration = current_trade['exit_date'] - current_trade['entry_date']
                current_trade['duration_hours'] = duration.total_seconds() / 3600

                trades.append(current_trade)
                current_trade = None

        return pd.DataFrame(trades)

    def _calculate_metrics(
        self,
        equity_curve: pd.Series,
        trades: pd.DataFrame
    ) -> dict:
        """Calculate performance metrics."""
        returns = equity_curve.pct_change().dropna()

        # Basic metrics
        total_return = (equity_curve.iloc[-1] / self.initial_capital - 1) * 100

        # Annualized metrics (assuming hourly data)
        hours_per_year = 365 * 24
        n_periods = len(equity_curve)
        years = n_periods / hours_per_year if n_periods > 0 else 1

        annual_return = ((equity_curve.iloc[-1] / self.initial_capital) ** (1/years) - 1) * 100 if years > 0 else 0
        annual_vol = returns.std() * np.sqrt(hours_per_year) * 100
        sharpe_ratio = (annual_return / annual_vol) if annual_vol > 0 else 0

        # Drawdown
        cummax = equity_curve.cummax()
        drawdown = (equity_curve - cummax) / cummax
        max_drawdown = drawdown.min() * 100

        # Trade statistics
        if len(trades) > 0:
            n_trades = len(trades)
            win_rate = (trades['pnl'] > 0).mean() * 100
            avg_win = trades[trades['pnl'] > 0]['pnl'].mean() if len(trades[trades['pnl'] > 0]) > 0 else 0
            avg_loss = abs(trades[trades['pnl'] <= 0]['pnl'].mean()) if len(trades[trades['pnl'] <= 0]) > 0 else 0
            profit_factor = (avg_win / avg_loss) if avg_loss > 0 else 0
            avg_trade_pnl = trades['pnl'].mean()
            avg_duration = trades['duration_hours'].mean() if 'duration_hours' in trades else 0
        else:
            n_trades = 0
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
            avg_trade_pnl = 0
            avg_duration = 0

        return {
            'total_return_pct': total_return,
            'annual_return_pct': annual_return,
            'annual_volatility_pct': annual_vol,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown_pct': max_drawdown,
            'n_trades': n_trades,
            'win_rate_pct': win_rate,
            'avg_win_usd': avg_win,
            'avg_loss_usd': avg_loss,
            'profit_factor': profit_factor,
            'avg_trade_pnl_usd': avg_trade_pnl,
            'avg_duration_hours': avg_duration,
            'final_equity': equity_curve.iloc[-1]
        }


if __name__ == "__main__":
    """Run backtester from command line."""
    import sys
    from pathlib import Path

    # Add project root to path
    sys.path.append(str(Path(__file__).parent.parent.parent))

    from src.data.cache import DataCache
    from src.features.spread import SpreadCalculator
    from src.utils.config import get_config

    # Parse arguments
    import argparse
    parser = argparse.ArgumentParser(description='Run backtest')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--html', help='Output HTML report path')
    args = parser.parse_args()

    # Load config
    config = get_config(args.config)
    cache = DataCache()

    # Load data
    print("Loading data from cache...")
    btc_data = cache.load_ohlcv(
        config.get("exchange", "binance"),
        "BTC/USDT",
        config.get("timeframe", "1h")
    )
    eth_data = cache.load_ohlcv(
        config.get("exchange", "binance"),
        "ETH/USDT",
        config.get("timeframe", "1h")
    )

    if btc_data.empty or eth_data.empty:
        print("Error: No data in cache. Run 'python -m src.runtime.batch_scanner' first to populate cache.")
        sys.exit(1)

    # Apply date filters if specified
    if args.start_date:
        start = pd.to_datetime(args.start_date, utc=True)
        btc_data = btc_data[btc_data.index >= start]
        eth_data = eth_data[eth_data.index >= start]

    if args.end_date:
        end = pd.to_datetime(args.end_date, utc=True)
        btc_data = btc_data[btc_data.index <= end]
        eth_data = eth_data[eth_data.index <= end]

    # Calculate signals
    print("Calculating signals...")
    signals = SpreadCalculator.calculate_all_signals(
        btc_prices=btc_data['close'],
        eth_prices=eth_data['close'],
        beta_window=config.get("windows.ols_beta", 200),
        zscore_window=config.get("windows.zscore", 100)
    )

    # Run backtest
    print("Running backtest...")
    backtester = VectorizedBacktester(
        initial_capital=config.get("backtest.initial_capital", 100000),
        fee_bps=config.get("costs.fee_bps", 10),
        slippage_bps=config.get("costs.slippage_bps", 5),
        target_sigma_usd=config.get("risk.target_sigma_usd", 200),
        max_notional_per_leg=config.get("risk.max_notional_usd_per_leg", 25000)
    )

    results = backtester.run_backtest(
        signals,
        z_in=config.get("thresholds.z_in", 2.0),
        z_out=config.get("thresholds.z_out", 0.5),
        z_stop=config.get("thresholds.z_stop", 3.5)
    )

    # Print results
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    for key, value in results.metrics.items():
        print(f"{key:25s}: {value:,.2f}" if isinstance(value, (int, float)) else f"{key:25s}: {value}")
    print("="*60)

    # Optional HTML report
    if args.html:
        try:
            from src.backtest.report import render_single_pair_report
            render_single_pair_report(
                signals=signals,
                results=results,
                pair_name="BTC-ETH",
                out_html=args.html,
                z_in=float(config.get("thresholds.z_in", 2.0)),
                z_out=float(config.get("thresholds.z_out", 0.5)),
                z_stop=float(config.get("thresholds.z_stop", 3.5)),
            )
            print(f"HTML report saved to: {args.html}")
        except Exception as e:
            print(f"Failed to write HTML report: {e}")
