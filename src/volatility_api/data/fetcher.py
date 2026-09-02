"""Data fetchers for multiple sources"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd
import yfinance as yf


class DataFetcher(ABC):
    """Abstract base class for data fetchers"""

    @abstractmethod
    def fetch(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch historical price data for a symbol"""
        pass


class YFinanceFetcher(DataFetcher):
    """Fetcher using yfinance API"""

    def fetch(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch data from yfinance.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with historical price data
        """
        try:
            data = yf.download(symbol, start=start_date, end=end_date, progress=False)
            return data
        except Exception as e:
            raise RuntimeError(f"Failed to fetch data for {symbol}: {str(e)}")


class AlphaVantageFetcher(DataFetcher):
    """Fetcher using Alpha Vantage API"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch data from Alpha Vantage.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with historical price data
        """
        # Implementation pending
        raise NotImplementedError("Alpha Vantage fetcher not yet implemented")
