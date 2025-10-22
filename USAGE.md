# Usage Guide

## Quick Start

### 1. Installation

```bash
# Run the setup script
./setup.sh

# Or manually:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration

Edit `.env` with your credentials:
```
EXCHANGE=binance
API_KEY=your_api_key_here
API_SECRET=your_api_secret_here
NOTIFY_SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

Adjust strategy parameters in `config.yaml`:
- `windows.ols_beta`: Rolling window for hedge ratio (default: 200)
- `windows.zscore`: Rolling window for z-score (default: 100)
- `thresholds.z_in`: Entry threshold (default: 2.0)
- `thresholds.z_out`: Exit threshold (default: 0.5)
- `thresholds.z_stop`: Stop loss threshold (default: 3.5)

### 3. Data Collection

Update the data cache:
```bash
python main.py cache --update
```

Check cache statistics:
```bash
python main.py cache --stats
```

### 4. Backtesting

Run a backtest with current parameters:
```bash
python main.py backtest
```

Run backtest with specific date range:
```bash
python main.py backtest --start-date 2024-01-01 --end-date 2024-12-31 --output results/backtest.json
```

### 5. Live Trading Scanner

Execute a single scan:
```bash
python main.py scan
```

Dry run mode (no notifications):
```bash
python main.py scan --dry-run
```

### 6. Scheduled Execution

Add to crontab for hourly execution:
```bash
crontab -e
```

Add this line:
```
1 * * * * cd /path/to/trading_signals && /path/to/venv/bin/python main.py scan >> logs/cron.log 2>&1
```

## Command Reference

### Scanner Command
```bash
python main.py scan [options]

Options:
  --config CONFIG     Config file path (default: config.yaml)
  --dry-run          Dry run mode, no notifications sent
```

### Backtest Command
```bash
python main.py backtest [options]

Options:
  --config CONFIG         Config file path
  --start-date START      Start date (YYYY-MM-DD)
  --end-date END         End date (YYYY-MM-DD)
  --output OUTPUT        Output file for results
```

### Cache Command
```bash
python main.py cache [options]

Options:
  --update               Update cache with latest data
  --stats               Show cache statistics
  --symbols SYMBOLS      Symbols to update (default: BTC/USDT ETH/USDT)
```

## Trade Signals

The system generates four types of signals:

1. **ENTER_LONG_SPREAD**: Long ETH, Short BTC (when z < -2)
2. **ENTER_SHORT_SPREAD**: Short ETH, Long BTC (when z > 2)
3. **EXIT_POSITION**: Close position (when |z| < 0.5)
4. **STOP_LOSS**: Force close (when |z| > 3.5)

## Output Files

- **Trade Tickets**: `signals/ticket_YYYYMMDD_HHMMSS_*.txt`
- **Signal JSON**: `signals/signal_YYYYMMDD_HHMMSS_*.json`
- **Run Logs**: `logs/runs/run_YYYYMMDD_HHMMSS.json`
- **Scanner Logs**: `logs/scanner.log`

## Performance Metrics

The backtester provides these metrics:
- Total Return (%)
- Annual Return (%)
- Sharpe Ratio
- Maximum Drawdown (%)
- Number of Trades
- Win Rate (%)
- Average Win/Loss
- Profit Factor

## Risk Management

The system includes several risk controls:
- Position size limited by `max_notional_per_leg`
- Volatility-based sizing with `target_sigma_usd`
- ADV (Average Daily Volume) constraints
- Stop loss at extreme z-scores
- Fee and slippage assumptions

## Troubleshooting

### No Data Error
```bash
# Update the cache first
python main.py cache --update
```

### API Connection Issues
- Check your `.env` file for correct API credentials
- Ensure your IP is whitelisted on the exchange
- Check rate limits

### No Signals Generated
- Review z-score thresholds in `config.yaml`
- Check if minimum bars requirement is met
- Verify ADV filters aren't too restrictive

## Production Checklist

- [ ] API keys configured and tested
- [ ] Notification webhooks verified
- [ ] Backtest results acceptable
- [ ] Risk parameters reviewed
- [ ] Cron job scheduled
- [ ] Monitoring/alerting setup
- [ ] Log rotation configured
- [ ] State persistence verified