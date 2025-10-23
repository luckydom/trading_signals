#!/usr/bin/env python3
"""
Main entry point for the BTC-ETH Statistical Arbitrage Trading System.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='BTC-ETH Statistical Arbitrage Trading System',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Scanner command
    scanner_parser = subparsers.add_parser('scan', help='Run trading scanner')
    scanner_parser.add_argument('--config', default='config.yaml', help='Config file path')
    scanner_parser.add_argument('--dry-run', action='store_true', help='Dry run mode')

    # Backtest command
    backtest_parser = subparsers.add_parser('backtest', help='Run backtest')
    backtest_parser.add_argument('--config', default='config.yaml', help='Config file path')
    backtest_parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    backtest_parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    backtest_parser.add_argument('--output', help='Output report file')

    # Cache command
    cache_parser = subparsers.add_parser('cache', help='Manage data cache')
    cache_parser.add_argument('--update', action='store_true', help='Update cache')
    cache_parser.add_argument('--stats', action='store_true', help='Show cache statistics')
    cache_parser.add_argument('--symbols', nargs='+', default=['BTC/USDT', 'ETH/USDT'],
                             help='Symbols to update')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'scan':
        from src.runtime.scanner import Scanner
        scanner = Scanner(config_path=args.config, dry_run=args.dry_run)
        scanner.run()

    elif args.command == 'backtest':
        from src.backtest.simulator import VectorizedBacktester
        from src.data.cache import DataCache
        from src.features.spread import SpreadCalculator
        from src.utils.config import get_config
        import pandas as pd

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
            print("Error: No data in cache. Run 'cache --update' first.")
            return

        # Apply date filters if specified (make timezone-aware)
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

        # Save results if output specified
        if args.output:
            import json
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save metrics
            with open(output_path, 'w') as f:
                json.dump(results.metrics, f, indent=2)
            print(f"\nResults saved to: {output_path}")

            # Save equity curve
            equity_path = output_path.with_suffix('.csv')
            results.equity_curve.to_csv(equity_path)
            print(f"Equity curve saved to: {equity_path}")

    elif args.command == 'cache':
        from src.data.exchange import ExchangeClient
        from src.data.cache import DataCache
        from src.utils.config import get_config

        config = get_config()
        cache = DataCache()

        if args.stats:
            stats = cache.get_cache_stats()
            print("\nCache Statistics:")
            print("="*60)
            print(f"Directory: {stats['cache_dir']}")
            print(f"Format: {stats['format']}")
            print(f"\nCached files:")
            for file_info in stats['files']:
                if 'file' in file_info:
                    print(f"  {file_info['file']}:")
                else:
                    print(f"  {file_info['table']}:")
                print(f"    Rows: {file_info['rows']}")
                print(f"    Start: {file_info['start']}")
                print(f"    End: {file_info['end']}")
                if 'size_mb' in file_info:
                    print(f"    Size: {file_info['size_mb']:.2f} MB")
            print("="*60)

        if args.update:
            print("Updating cache...")
            exchange = ExchangeClient()
            # Need more bars for proper signal generation (beta_window + zscore_window + buffer)
            min_bars = 500  # Increase to 500 bars for better signal generation
            data = cache.update_cache(
                exchange,
                args.symbols,
                config.get("timeframe", "1h"),
                lookback_bars=min_bars
            )
            print(f"Cache updated for {len(data)} symbols with {min_bars} bars each")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()