"""HTML reporting helpers for backtests."""

from typing import Optional
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_single_pair_report(
    signals: pd.DataFrame,
    results,
    pair_name: str,
    out_html: str,
    z_in: float = 2.0,
    z_out: float = 0.5,
    z_stop: float = 3.5,
) -> None:
    """Render a single-pair HTML report with equity and z-score.

    Args:
        signals: DataFrame including columns ['btc_price','eth_price','beta','zscore','spread','spread_std']
        results: BacktestResults from VectorizedBacktester
        pair_name: Display name for the pair
        out_html: Output HTML path
        z_in/z_out/z_stop: Thresholds to overlay on z chart
    """
    # Align equity curve with signals index
    eq = results.equity_curve

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.08,
                        subplot_titles=(f"Equity Curve - {pair_name}", "Z-score and thresholds"))

    # Equity
    fig.add_trace(go.Scatter(x=eq.index, y=eq.values, name="Equity", mode="lines"), row=1, col=1)

    # Z-score
    z = signals['zscore']
    fig.add_trace(go.Scatter(x=z.index, y=z.values, name="Z", mode="lines"), row=2, col=1)
    # Thresholds
    for level, name, color in [(z_in, "+z_in", "orange"), (-z_in, "-z_in", "orange"),
                               (z_out, "+z_out", "green"), (-z_out, "-z_out", "green"),
                               (z_stop, "+z_stop", "red"), (-z_stop, "-z_stop", "red")]:
        fig.add_hline(y=level, line=dict(color=color, dash="dot"), row=2, col=1)

    fig.update_layout(height=700, title_text=f"Backtest Report: {pair_name}")
    fig.write_html(out_html, include_plotlyjs="cdn")


def render_multi_report(summary_df: pd.DataFrame, out_html: str) -> None:
    """Render a simple multi-pair HTML summary with a metrics table.

    Args:
        summary_df: DataFrame of metrics per pair (pair, n_trades, sharpe, return, mdd, etc.)
        out_html: Output HTML path
    """
    # Build a simple HTML page with a table
    cols = [
        "pair", "n_trades", "win_rate_pct", "sharpe_ratio",
        "total_return_pct", "max_drawdown_pct", "annual_return_pct",
    ]
    present = [c for c in cols if c in summary_df.columns]
    html_table = summary_df[present].to_html(index=False, float_format=lambda x: f"{x:,.2f}")

    html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Multi-Pair Backtest Summary</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 20px; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; }}
      th {{ background-color: #f2f2f2; }}
    </style>
  </head>
  <body>
    <h1>Multi-Pair Backtest Summary</h1>
    {html_table}
  </body>
  </html>
"""
    with open(out_html, "w") as f:
        f.write(html)

