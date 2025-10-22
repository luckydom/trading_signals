#!/bin/bash
# Setup script for BTC-ETH Statistical Arbitrage Trading System

echo "Setting up BTC-ETH Statistical Arbitrage Trading System..."

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating directories..."
mkdir -p data/cache
mkdir -p signals
mkdir -p reports
mkdir -p logs/runs

# Copy environment file
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "Please edit .env with your API keys and settings"
fi

# Create initial state file
echo '{"current_state": "neutral"}' > data/state.json

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your exchange API keys and notification webhooks"
echo "2. Review and adjust config.yaml for your strategy parameters"
echo "3. Run 'python main.py cache --update' to fetch initial data"
echo "4. Run 'python main.py backtest' to test the strategy"
echo "5. Run 'python main.py scan' to execute a live scan"
echo ""
echo "For scheduled hourly runs, add to crontab:"
echo "1 * * * * cd $(pwd) && venv/bin/python main.py scan >> logs/cron.log 2>&1"