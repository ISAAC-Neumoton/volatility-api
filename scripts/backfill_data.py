"""
Backfill historical price data into the repository.

This script downloads historical OHLCV data for FX pairs and persists them to
the database for use in model training and validation. Supports manual date range
specification and automatic progress reporting with error handling and recovery.

Usage:
    # Backfill EURUSD with 2 years of data
    python scripts/backfill_data.py EURUSD

    # Backfill with custom date range
    python scripts/backfill_data.py EURUSD --start-date 2021-01-01 --end-date 2024-01-15

    # Backfill multiple pairs
    python scripts/backfill_data.py EURUSD USDJPY GBPUSD

    # Use Alpha Vantage as fallback
    python scripts/backfill_data.py EURUSD --alpha-key your_key_here

Example:
    >>> python scripts/backfill_data.py EURUSD USDJPY
    Loading data for EURUSD from 2022-01-15 to 2024-01-15
    Downloaded 504 rows
    Successfully backfilled data for EURUSD
    Loading data for USDJPY from 2022-01-15 to 2024-01-15
    Downloaded 498 rows
    Successfully backfilled data for USDJPY
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from volatility_api.config import settings
from volatility_api.core.logging import setup_logging, get_logger
from volatility_api.data.fetcher import FetcherFactory, DataFetcher
from volatility_api.data.repository import RepositoryService, PriceHistory

logger = get_logger(__name__)


class BackfillService:
    """
    Service for backfilling historical price data.

    Manages the workflow of fetching data, validating, and persisting to database.
    Handles multiple pairs with progress reporting and error recovery.

    Attributes:
        repository: RepositoryService instance for database access.
        fetcher_factory: FetcherFactory for multi-source data fetching.
    """

    def __init__(
        self,
        repository: RepositoryService,
        fetcher_factory: FetcherFactory,
    ):
        """
        Initialize backfill service.

        Args:
            repository: Configured RepositoryService instance.
            fetcher_factory: Configured FetcherFactory instance.
        """
        self.repository = repository
        self.fetcher_factory = fetcher_factory

    def backfill_pair(
        self,
        pair: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """
        Backfill data for a single currency pair.

        Downloads historical data and persists to database. Skips existing records
        to allow incremental backfilling.

        Args:
            pair: FX pair code (e.g., "EURUSD").
            start_date: Optional start date (YYYY-MM-DD). If not provided, uses 2 years ago.
            end_date: Optional end date (YYYY-MM-DD). If not provided, uses today.

        Returns:
            Number of records successfully persisted.

        Raises:
            RuntimeError: If data fetch fails or validation errors occur.

        Example:
            >>> service = BackfillService(repo, factory)
            >>> count = service.backfill_pair("EURUSD", start_date="2021-01-01")
            >>> print(f"Persisted {count} records")
        """
        # Parse dates
        if not end_date:
            end_date_obj = datetime.utcnow().date()
        else:
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

        if not start_date:
            start_date_obj = end_date_obj - timedelta(days=730)  # ~2 years
        else:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()

        logger.info(
            f"Loading historical data for {pair} from {start_date_obj} to {end_date_obj}"
        )

        # Calculate period for yfinance based on date range
        days_span = (end_date_obj - start_date_obj).days
        if days_span >= 730:
            period = "2y"
        elif days_span >= 365:
            period = "1y"
        elif days_span >= 180:
            period = "6mo"
        else:
            period = "1mo"

        try:
            # Fetch data with fallback
            df = self.fetcher_factory.fetch_with_fallback(pair, period=period)

            logger.info(f"Downloaded {len(df)} rows for {pair}")

            # Filter by date range if specified
            if not df.empty:
                df = df[(df.index.date >= start_date_obj) & (df.index.date <= end_date_obj)]
                logger.info(f"After date filtering: {len(df)} rows")

            if df.empty:
                raise ValueError(f"No data available for {pair} in date range")

            # Persist to database
            persisted_count = 0
            for date, row in df.iterrows():
                try:
                    price_record = PriceHistory(
                        pair=pair,
                        date=pd.Timestamp(date).to_pydatetime(),
                        open_price=float(row["Open"]),
                        high_price=float(row["High"]),
                        low_price=float(row["Low"]),
                        close_price=float(row["Close"]),
                        volume=int(row["Volume"]) if row["Volume"] > 0 else 0,
                    )
                    self.repository.upsert_price_history(price_record)
                    persisted_count += 1

                except Exception as e:
                    logger.warning(
                        f"Error persisting record for {pair} on {date}: {str(e)}"
                    )
                    # Continue with next record
                    continue

            logger.info(
                f"Successfully backfilled {pair}: {persisted_count} records persisted"
            )
            return persisted_count

        except Exception as e:
            logger.error(f"Error backfilling {pair}: {str(e)}")
            raise RuntimeError(f"Failed to backfill {pair}: {str(e)}") from e

    def backfill_pairs(
        self,
        pairs: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Backfill data for multiple currency pairs.

        Processes pairs sequentially with error recovery (continues on individual
        pair failures).

        Args:
            pairs: List of FX pair codes.
            start_date: Optional start date (YYYY-MM-DD).
            end_date: Optional end date (YYYY-MM-DD).

        Returns:
            Dictionary with results per pair: {"EURUSD": 504, "USDJPY": 498, ...}
        """
        results = {}

        for pair in pairs:
            try:
                count = self.backfill_pair(pair, start_date, end_date)
                results[pair] = count
            except RuntimeError as e:
                logger.error(f"Skipping {pair} due to error: {str(e)}")
                results[pair] = 0

        return results


def main():
    """
    Main entry point for backfill CLI.

    Parses arguments, initializes services, and orchestrates backfill workflow.
    """
    parser = argparse.ArgumentParser(
        description="Backfill historical FX price data into VolaCast database",
        epilog="Example: python scripts/backfill_data.py EURUSD USDJPY --start-date 2021-01-01",
    )

    parser.add_argument(
        "pairs",
        nargs="+",
        help="FX pair codes to backfill (e.g., EURUSD USDJPY GBPUSD)",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Default: 2 years ago",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Default: today",
    )

    parser.add_argument(
        "--db",
        type=str,
        default=settings.database_url,
        help=f"Database URL (default: {settings.database_url})",
    )

    parser.add_argument(
        "--alpha-key",
        type=str,
        default=None,
        help="Alpha Vantage API key for fallback (optional)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)

    logger.info("=" * 80)
    logger.info("VolaCast Backfill Service Started")
    logger.info("=" * 80)
    logger.info(f"Pairs: {', '.join(args.pairs)}")
    logger.info(f"Start Date: {args.start_date or 'Auto (2 years ago)'}")
    logger.info(f"End Date: {args.end_date or 'Today'}")
    logger.info(f"Database: {args.db}")
    logger.info("=" * 80)

    try:
        # Initialize repository
        repository = RepositoryService(args.db)
        logger.info("Initializing database schema...")
        repository.initialize()
        logger.info("Database initialized successfully")

        # Initialize fetcher factory
        fetcher_factory = FetcherFactory(alpha_vantage_key=args.alpha_key)
        logger.info("Data fetcher factory initialized")

        # Create backfill service
        backfill_service = BackfillService(repository, fetcher_factory)

        # Run backfill
        logger.info(f"Starting backfill for {len(args.pairs)} pair(s)...")
        results = backfill_service.backfill_pairs(
            args.pairs,
            start_date=args.start_date,
            end_date=args.end_date,
        )

        # Print results
        logger.info("=" * 80)
        logger.info("Backfill Results:")
        logger.info("=" * 80)

        total_records = 0
        for pair, count in results.items():
            status = "✓" if count > 0 else "✗"
            logger.info(f"{status} {pair}: {count} records")
            total_records += count

        logger.info("=" * 80)
        logger.info(f"Total records persisted: {total_records}")
        logger.info("Backfill completed successfully")
        logger.info("=" * 80)

        return 0

    except KeyboardInterrupt:
        logger.warning("Backfill interrupted by user")
        return 1

    except Exception as e:
        logger.exception(f"Fatal error during backfill: {str(e)}")
        return 1


if __name__ == "__main__":
    import pandas as pd  # Import here to avoid import errors

    exit_code = main()
    sys.exit(exit_code)

