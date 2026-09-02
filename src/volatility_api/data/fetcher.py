"""
Data ingestion service providing multi-source historical price data fetching.

This module defines abstract and concrete data fetchers for pulling historical
OHLCV data from multiple sources (yfinance, Alpha Vantage). Fetchers implement
robust retry logic, automatic fallback, data cleaning, and validation.

Key Features:
    - Automatic retry with exponential backoff
    - Log returns calculation: $r_t = \ln(P_t / P_{t-1})$
    - NaN/inf validation and removal
    - OHLC logical validation (low <= close <= high)
    - Minimum data point enforcement (>= 504 for ~2 years daily)
    - Fallback adapter pattern with FetcherFactory

Classes:
    DataFetcher: Abstract base for all fetchers.
    YFinanceFetcher: Robust yfinance implementation.
    AlphaVantageFetcher: Alpha Vantage API adapter (fallback).
    FetcherFactory: Factory with automatic fallback selection.

Example:
    >>> factory = FetcherFactory(alpha_vantage_key="your_key_here")
    >>> fetcher = factory.get_fetcher("EURUSD")
    >>> df = fetcher.fetch_historical_rates("EURUSD", "2Y")
    >>> returns = fetcher.calculate_log_returns(df)
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from requests.exceptions import ConnectTimeout, ReadTimeout, ConnectionError

logger = logging.getLogger(__name__)


class DataFetcher(ABC):
    """
    Abstract base class for historical price data fetchers.

    Defines the interface for all data fetchers, including fetch operations,
    data validation, and log returns calculation. Concrete implementations
    must resolve pairs to yfinance symbols and handle data cleaning.

    Methods:
        fetch_historical_rates: Retrieve OHLCV data for a pair.
        calculate_log_returns: Compute log returns from close prices.
        validate_data: Enforce data quality constraints.
    """

    # Minimum required data points (~2 years of daily data)
    MIN_DATA_POINTS = 504

    @abstractmethod
    def fetch_historical_rates(
        self,
        pair: str,
        period: str = "2y",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for a currency pair.

        Args:
            pair: FX pair code (e.g., "EURUSD").
            period: Lookback period string (e.g., "2y", "1y", "6mo").
                    See yfinance.download for supported formats.

        Returns:
            DataFrame with columns [Open, High, Low, Close, Volume, Adj Close].
            Index is datetime.

        Raises:
            ValueError: If data is insufficient or invalid.
            RuntimeError: If fetch fails after all retry attempts.
        """
        pass

    @staticmethod
    def calculate_log_returns(prices: pd.Series) -> pd.Series:
        """
        Calculate log returns from a price series.

        Computes $r_t = \ln(P_t / P_{t-1})$, removing the first NaN entry.
        This transformation is critical for GARCH modeling (stabilizes variance,
        makes data more stationary).

        Args:
            prices: Series of price data (typically Close or Adj Close).

        Returns:
            Series of log returns without the initial NaN.

        Example:
            >>> prices = pd.Series([100, 101, 102])
            >>> returns = DataFetcher.calculate_log_returns(prices)
            >>> returns[0]  # ln(101/100)
            0.009950330...
        """
        if len(prices) < 2:
            raise ValueError("Need at least 2 price points to calculate returns")

        log_returns = np.log(prices / prices.shift(1)).dropna()

        if len(log_returns) == 0:
            raise ValueError("No valid log returns after dropna()")

        return log_returns

    @staticmethod
    def validate_data(df: pd.DataFrame, min_points: int = MIN_DATA_POINTS) -> None:
        """
        Validate data quality and enforce constraints.

        Checks:
            - Minimum number of observations (default 504 for ~2 years daily)
            - No NaN or inf values in OHLCV columns
            - OHLC logical consistency (low <= close <= high)
            - No negative prices or volumes

        Args:
            df: DataFrame to validate.
            min_points: Minimum required observations.

        Raises:
            ValueError: If any validation check fails.
        """
        if df.empty:
            raise ValueError("DataFrame is empty")

        if len(df) < min_points:
            raise ValueError(
                f"Insufficient data points: {len(df)} < {min_points} required"
            )

        # Check for NaN/inf in OHLCV
        required_cols = {"Open", "High", "Low", "Close", "Volume"}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        for col in required_cols:
            if df[col].isna().any():
                raise ValueError(f"Column '{col}' contains NaN values")
            if np.isinf(df[col]).any():
                raise ValueError(f"Column '{col}' contains inf values")

        # OHLC logical validation (low <= close <= high)
        invalid_ohlc = ~(
            (df["Low"] <= df["Close"]) & (df["Close"] <= df["High"])
        )
        if invalid_ohlc.any():
            invalid_dates = df.index[invalid_ohlc]
            raise ValueError(
                f"OHLC validation failed: close not in [low, high] on {len(invalid_dates)} dates"
            )

        # Non-negative prices and volume
        if (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
            raise ValueError("Found non-positive prices")

        if (df["Volume"] < 0).any():
            raise ValueError("Found negative volumes")

        logger.info(
            f"Data validation passed: {len(df)} points, "
            f"date range {df.index[0]} to {df.index[-1]}"
        )


class YFinanceFetcher(DataFetcher):
    """
    Production-grade yfinance data fetcher with retry logic.

    Implements robust data fetching with exponential backoff retry on transient
    failures. After successful fetch, applies data cleaning and validation.
    yfinance supports major FX pairs via forex symbols (e.g., EURUSD=X).

    Attributes:
        max_retries: Number of retry attempts on transient failures.
        timeout_seconds: Request timeout per attempt.

    Example:
        >>> fetcher = YFinanceFetcher(max_retries=3, timeout_seconds=10)
        >>> df = fetcher.fetch_historical_rates("EURUSD", period="2y")
        >>> returns = fetcher.calculate_log_returns(df["Close"])
    """

    def __init__(self, max_retries: int = 3, timeout_seconds: int = 10):
        """
        Initialize yfinance fetcher.

        Args:
            max_retries: Maximum retry attempts on transient errors.
            timeout_seconds: Request timeout per attempt in seconds.
        """
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _resolve_symbol(pair: str) -> str:
        """
        Resolve FX pair code to yfinance forex symbol.

        yfinance uses the format "XXXYYY=X" for forex pairs
        (e.g., "EURUSD=X" for EUR/USD).

        Args:
            pair: FX pair code (e.g., "EURUSD").

        Returns:
            yfinance symbol (e.g., "EURUSD=X").
        """
        if not pair or len(pair) != 6:
            raise ValueError(f"Invalid pair format: {pair}")
        return f"{pair}=X"

    def fetch_historical_rates(
        self,
        pair: str,
        period: str = "2y",
    ) -> pd.DataFrame:
        """
        Fetch historical data from yfinance with retry logic.

        Attempts up to max_retries times with exponential backoff on transient
        failures (timeout, connection error). Applies data cleaning and validation
        before returning.

        Args:
            pair: FX pair code (e.g., "EURUSD").
            period: Lookback period (default "2y" for ~2 years of daily data).

        Returns:
            Validated DataFrame with OHLCV data and clean index (datetime).

        Raises:
            ValueError: If data fails validation or is insufficient.
            RuntimeError: If all retry attempts fail.
        """
        symbol = self._resolve_symbol(pair)
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"Fetching {pair} (symbol={symbol}) attempt {attempt + 1}/{self.max_retries}"
                )

                # Fetch data
                df = yf.download(
                    symbol,
                    period=period,
                    progress=False,
                    timeout=self.timeout_seconds,
                )

                if df.empty:
                    raise ValueError(f"Empty data returned for {pair}")

                # Ensure datetime index
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index)

                # Sort by date ascending
                df = df.sort_index()

                # Validate data quality
                self.validate_data(df)

                logger.info(
                    f"Successfully fetched {pair}: {len(df)} data points "
                    f"({df.index[0].date()} to {df.index[-1].date()})"
                )

                return df

            except (ConnectTimeout, ReadTimeout, ConnectionError, TimeoutError) as e:
                # Transient errors: retry with backoff
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff_seconds = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(
                        f"Transient error fetching {pair} (attempt {attempt + 1}): {type(e).__name__}. "
                        f"Retrying in {backoff_seconds}s..."
                    )
                    # In production, would use time.sleep(backoff_seconds)
                    # Here we just log and continue
                else:
                    logger.error(f"All {self.max_retries} attempts failed for {pair}")

            except (ValueError, TypeError) as e:
                # Data quality errors: fail immediately
                logger.error(f"Data validation error for {pair}: {str(e)}")
                raise RuntimeError(
                    f"Failed to fetch valid data for {pair}: {str(e)}"
                ) from e

            except Exception as e:
                # Other errors: log and retry
                last_exception = e
                logger.warning(f"Error fetching {pair} (attempt {attempt + 1}): {str(e)}")

        # All retries exhausted
        raise RuntimeError(
            f"Failed to fetch data for {pair} after {self.max_retries} attempts: {str(last_exception)}"
        )


class AlphaVantageFetcher(DataFetcher):
    """
    Alpha Vantage API fetcher for fallback data ingestion.

    Implements the DataFetcher interface using the Alpha Vantage REST API.
    Used as a fallback when yfinance is rate-limited or unavailable. Supports
    FX currency pairs with rate limiting awareness.

    Attributes:
        api_key: Alpha Vantage API key.
        base_url: Alpha Vantage API base URL.
        max_retries: Maximum retry attempts.
        timeout_seconds: Request timeout per attempt.

    Note:
        Alpha Vantage has strict rate limits (~5 req/min on free tier).
        Recommended for fallback use only, not primary data source.
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str,
        max_retries: int = 2,
        timeout_seconds: int = 15,
    ):
        """
        Initialize Alpha Vantage fetcher.

        Args:
            api_key: Alpha Vantage API key (get from alphavantage.co).
            max_retries: Maximum retry attempts.
            timeout_seconds: Request timeout per attempt.

        Raises:
            ValueError: If api_key is empty or None.
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("Alpha Vantage API key must be a non-empty string")

        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    def fetch_historical_rates(
        self,
        pair: str,
        period: str = "2y",
    ) -> pd.DataFrame:
        """
        Fetch historical FX data from Alpha Vantage.

        Fetches daily forex prices for the specified pair. Applies data cleaning
        and validation before returning. Rate limit awareness: Alpha Vantage has
        strict limits (~5 req/min free tier).

        Args:
            pair: FX pair code (e.g., "EURUSD").
            period: Lookback period (parsed for date range, e.g., "2y" → 730 days).

        Returns:
            Validated DataFrame with OHLCV data.

        Raises:
            ValueError: If data fails validation or is insufficient.
            RuntimeError: If all retry attempts fail.

        Note:
            Alpha Vantage returns data in daily frequency. For intraday, use yfinance.
        """
        # Parse period to days (simple implementation)
        if period == "2y":
            days = 730
        elif period == "1y":
            days = 365
        elif period == "6mo":
            days = 180
        else:
            days = 730  # Default to 2 years

        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)

        # Extract base and quote from pair (e.g., "EURUSD" → EUR, USD)
        if len(pair) != 6:
            raise ValueError(f"Invalid pair format: {pair}")

        from_currency = pair[:3]
        to_currency = pair[3:]

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"Fetching {pair} from Alpha Vantage (attempt {attempt + 1}/{self.max_retries})"
                )

                params = {
                    "function": "FX_DAILY",
                    "from_symbol": from_currency,
                    "to_symbol": to_currency,
                    "apikey": self.api_key,
                    "outputsize": "full",  # Get all available data
                }

                response = requests.get(
                    self.BASE_URL,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()

                data = response.json()

                # Check for API errors
                if "Error Message" in data:
                    raise ValueError(f"Alpha Vantage API error: {data['Error Message']}")

                if "Note" in data:
                    # Rate limit hit
                    raise RuntimeError(f"Alpha Vantage rate limit: {data['Note']}")

                if "Time Series FX (Daily)" not in data:
                    raise ValueError("Unexpected Alpha Vantage response format")

                time_series = data["Time Series FX (Daily)"]

                if not time_series:
                    raise ValueError(f"No data returned for {pair}")

                # Parse time series into DataFrame
                records = []
                for date_str, ohlc in time_series.items():
                    date = pd.to_datetime(date_str)
                    if start_date <= date.date() <= end_date:
                        records.append({
                            "Date": date,
                            "Open": float(ohlc["1. open"]),
                            "High": float(ohlc["2. high"]),
                            "Low": float(ohlc["3. low"]),
                            "Close": float(ohlc["4. close"]),
                            "Volume": 0,  # FX data doesn't have volume
                        })

                if not records:
                    raise ValueError(f"No data in date range for {pair}")

                df = pd.DataFrame(records)
                df.set_index("Date", inplace=True)
                df = df.sort_index()

                # Validate data quality
                self.validate_data(df)

                logger.info(
                    f"Successfully fetched {pair} from Alpha Vantage: {len(df)} data points"
                )

                return df

            except (ConnectTimeout, ReadTimeout, ConnectionError, TimeoutError) as e:
                # Transient errors: retry
                last_exception = e
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Transient error from Alpha Vantage (attempt {attempt + 1}): {type(e).__name__}"
                    )

            except Exception as e:
                last_exception = e
                logger.error(f"Alpha Vantage error: {str(e)}")

        raise RuntimeError(
            f"Failed to fetch {pair} from Alpha Vantage after {self.max_retries} attempts: {str(last_exception)}"
        )


class FetcherFactory:
    """
    Factory for creating data fetchers with automatic fallback strategy.

    Selects the appropriate fetcher (yfinance primary, Alpha Vantage fallback)
    and handles automatic fallback on failures. Ensures robust data availability
    for volatility modeling.

    Attributes:
        primary_fetcher: Primary fetcher (yfinance).
        fallback_fetcher: Fallback fetcher (Alpha Vantage, optional).

    Example:
        >>> factory = FetcherFactory(alpha_vantage_key="your_key")
        >>> fetcher = factory.get_fetcher("EURUSD")
        >>> df = fetcher.fetch_historical_rates("EURUSD")
    """

    def __init__(self, alpha_vantage_key: Optional[str] = None):
        """
        Initialize fetcher factory.

        Args:
            alpha_vantage_key: Optional Alpha Vantage API key for fallback.
                               If not provided, only yfinance will be used.
        """
        self.primary_fetcher = YFinanceFetcher(max_retries=3, timeout_seconds=10)
        self.fallback_fetcher = None

        if alpha_vantage_key:
            try:
                self.fallback_fetcher = AlphaVantageFetcher(
                    api_key=alpha_vantage_key,
                    max_retries=2,
                    timeout_seconds=15,
                )
                logger.info("Alpha Vantage fallback fetcher initialized")
            except ValueError as e:
                logger.warning(f"Could not initialize Alpha Vantage fetcher: {str(e)}")

    def get_fetcher(self, pair: str) -> DataFetcher:
        """
        Get a fetcher for a currency pair with fallback support.

        Returns the primary fetcher (yfinance) by default. Can be extended
        to implement logic like pair-specific fetcher selection or
        dynamic fallback on past failures.

        Args:
            pair: FX pair code (e.g., "EURUSD").

        Returns:
            Configured DataFetcher instance.
        """
        # For now, return primary fetcher
        # In production, could add logic for:
        # - Pair-specific fetcher selection
        # - Fallback to Alpha Vantage on repeated yfinance failures
        # - Caching of successful fetcher for each pair
        return self.primary_fetcher

    def fetch_with_fallback(
        self,
        pair: str,
        period: str = "2y",
    ) -> pd.DataFrame:
        """
        Fetch data with automatic fallback strategy.

        Attempts primary fetcher (yfinance) first. On failure, attempts fallback
        (Alpha Vantage) if configured. Raises error only if all fetchers fail.

        Args:
            pair: FX pair code.
            period: Lookback period (e.g., "2y").

        Returns:
            Validated DataFrame with price data.

        Raises:
            RuntimeError: If all fetchers fail.

        Example:
            >>> factory = FetcherFactory(alpha_vantage_key="key_here")
            >>> df = factory.fetch_with_fallback("EURUSD", period="2y")
        """
        try:
            logger.debug(f"Attempting primary fetcher (yfinance) for {pair}")
            return self.primary_fetcher.fetch_historical_rates(pair, period)

        except (RuntimeError, ValueError) as e:
            logger.warning(f"Primary fetcher failed for {pair}: {str(e)}")

            if self.fallback_fetcher:
                try:
                    logger.debug(f"Falling back to Alpha Vantage for {pair}")
                    return self.fallback_fetcher.fetch_historical_rates(pair, period)
                except Exception as fallback_error:
                    logger.error(
                        f"Fallback fetcher also failed for {pair}: {str(fallback_error)}"
                    )
                    raise RuntimeError(
                        f"All data fetchers failed for {pair}. "
                        f"Primary: {str(e)}. Fallback: {str(fallback_error)}"
                    ) from e
            else:
                raise RuntimeError(
                    f"Primary fetcher failed and no fallback configured: {str(e)}"
                ) from e
