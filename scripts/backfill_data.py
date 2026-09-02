"""Script to backfill historical data into the repository"""

import argparse
from datetime import datetime

from src.volatility_api.data.fetcher import YFinanceFetcher
from src.volatility_api.data.repository import DataRepository


def backfill_data(
    symbol: str,
    start_date: str,
    end_date: str,
    db_path: str = "volatility.db",
) -> None:
    """
    Backfill historical data for a symbol.

    Args:
        symbol: Stock ticker symbol
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        db_path: Path to SQLite database
    """
    print(f"Loading data for {symbol} from {start_date} to {end_date}")

    fetcher = YFinanceFetcher()
    repo = DataRepository(db_path)

    try:
        data = fetcher.fetch(symbol, start_date, end_date)
        print(f"Downloaded {len(data)} rows")

        repo.save_data(symbol, data)
        print(f"Successfully backfilled data for {symbol}")

    except Exception as e:
        print(f"Error backfilling data: {str(e)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical data")
    parser.add_argument("symbol", help="Stock ticker symbol")
    parser.add_argument("--start-date", default="2020-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2024-01-01", help="End date (YYYY-MM-DD)")
    parser.add_argument("--db", default="volatility.db", help="Database path")

    args = parser.parse_args()

    backfill_data(args.symbol, args.start_date, args.end_date, args.db)
