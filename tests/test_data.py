"""Tests for data fetching and repository"""

import pandas as pd
import pytest

from src.volatility_api.data.fetcher import YFinanceFetcher
from src.volatility_api.data.repository import DataRepository


def test_yfinance_fetcher():
    """Test yfinance data fetcher"""
    fetcher = YFinanceFetcher()
    # Use a small date range for testing
    data = fetcher.fetch("AAPL", "2023-01-01", "2023-01-10")

    assert isinstance(data, pd.DataFrame)
    assert len(data) > 0


def test_data_repository_init():
    """Test data repository initialization"""
    repo = DataRepository(":memory:")
    assert repo is not None
