# BTC-ETH Market-Neutral Statistical Arbitrage Scanner

An hourly BTC-ETH market-neutral statistical arbitrage (cointegration mean-reversion) scanner that outputs actionable trade tickets.

## Overview

This system implements a pairs trading strategy between BTC/USDT and ETH/USDT using:
- Rolling OLS for dynamic hedge ratio calculation
- Z-score based entry/exit signals
- Dollar-neutral positioning with volatility targeting
- Automated trade ticket generation and notifications

## Features

- **Hourly Data Ingestion**: Pulls 1h OHLCV data from Binance
- **Signal Generation**: Cointegration-based mean reversion signals
- **Risk Management**: Position sizing with volatility targeting and stop losses
- **Backtesting**: Vectorized backtester with walk-forward validation
- **Notifications**: Slack/Telegram alerts for trade signals
- **Observability**: Logging, dashboards, and performance metrics

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys and settings
```

## Configuration

Edit `config.yaml` to adjust strategy parameters:
- Window sizes for OLS and z-score calculations
- Entry/exit thresholds
- Risk parameters
- Cost assumptions

## Usage

### Run Scanner (Manual)
```bash
python -m src.runtime.scanner
```

### Run Backtest
```bash
python -m src.backtest.simulator --config config.yaml
```

### Schedule Hourly Runs
See deployment section for cron/systemd setup.

## Project Structure

```
stat-arb-btc-eth/
├── src/
│   ├── data/          # Data fetching and caching
│   ├── features/      # Signal calculations (beta, spread, z-score)
│   ├── strategy/      # Trading logic and position management
│   ├── backtest/      # Backtesting engine
│   ├── runtime/       # Scanner and notifications
│   └── utils/         # Utilities and helpers
├── tests/             # Unit tests
├── data/cache/        # Local data cache
├── signals/           # Trade tickets
└── reports/           # Dashboard and reports
```

## License

MIT License - See LICENSE file for details