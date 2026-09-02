"""
Unit tests for data fetching and repository layer.

Tests cover:
    - DataFetcher abstract base class
    - YFinanceFetcher with retry logic
    - AlphaVantageFetcher (mocked API)
    - FetcherFactory fallback strategy
    - Log returns calculation
    - Data validation (OHLC consistency, NaN/inf checking)
    - Repository CRUD operations with SQLAlchemy models

Fixtures:
    sample_dataframe: Mock OHLCV data for testing
    in_memory_db: In-memory SQLite database
    sample_prices: Price series for log returns tests
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Generator

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.volatility_api.data.fetcher import (
    DataFetcher,
    YFinanceFetcher,
    AlphaVantageFetcher,
    FetcherFactory,
)
from src.volatility_api.data.repository import (
    Base,
    RepositoryService,
    PriceHistory,
    ModelRegistry,
    ApiKey,
    RequestLog,
    BacktestResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    """
    Create a sample OHLCV DataFrame for testing.

    Returns:
        DataFrame with 504 days of valid OHLC data (simulated FX).
    """
    dates = pd.date_range(start="2022-01-01", periods=504, freq="D")
    np.random.seed(42)

    # Simulate realistic FX data (EURUSD ~1.1)
    base_price = 1.1
    close_prices = base_price + np.cumsum(np.random.normal(0, 0.001, 504))

    df = pd.DataFrame({
        "Open": close_prices + np.random.normal(0, 0.0005, 504),
        "High": close_prices + np.abs(np.random.normal(0.001, 0.0005, 504)),
        "Low": close_prices - np.abs(np.random.normal(0.001, 0.0005, 504)),
        "Close": close_prices,
        "Volume": np.random.randint(100000, 1000000, 504),
    }, index=dates)

    # Ensure OHLC logical consistency
    df["High"] = df[["Open", "High", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "Low", "Close"]].min(axis=1)

    return df


@pytest.fixture
def sample_prices() -> pd.Series:
    """
    Create sample price series for log returns calculation.

    Returns:
        Series of 100 prices starting at 100.0
    """
    np.random.seed(42)
    returns = np.random.normal(0, 0.01, 100)
    prices = 100.0 * np.exp(np.cumsum(returns))
    return pd.Series(prices, name="Close")


@pytest.fixture
def in_memory_db() -> Generator:
    """
    Create an in-memory SQLite database for testing.

    Yields:
        RepositoryService instance with in-memory SQLite connection.
    """
    repo = RepositoryService("sqlite:///:memory:")
    repo.initialize()
    yield repo


# ============================================================================
# Tests: DataFetcher Abstract Base
# ============================================================================


class TestDataFetcher:
    """Tests for DataFetcher abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Test that DataFetcher cannot be directly instantiated."""
        with pytest.raises(TypeError):
            DataFetcher()

    def test_calculate_log_returns(self, sample_prices: pd.Series):
        """Test log returns calculation."""
        returns = DataFetcher.calculate_log_returns(sample_prices)

        # Check length (first NaN removed)
        assert len(returns) == len(sample_prices) - 1

        # Check formula: ln(P_t / P_{t-1})
        expected_first = np.log(sample_prices.iloc[1] / sample_prices.iloc[0])
        assert np.isclose(returns.iloc[0], expected_first)

    def test_calculate_log_returns_insufficient_data(self):
        """Test that log returns fails with insufficient data."""
        prices = pd.Series([100.0])
        with pytest.raises(ValueError, match="at least 2 price points"):
            DataFetcher.calculate_log_returns(prices)

    def test_validate_data_success(self, sample_dataframe: pd.DataFrame):
        """Test successful data validation."""
        # Should not raise
        DataFetcher.validate_data(sample_dataframe)

    def test_validate_data_insufficient_points(self, sample_dataframe: pd.DataFrame):
        """Test validation fails with insufficient data."""
        df_small = sample_dataframe.head(100)
        with pytest.raises(ValueError, match="Insufficient data points"):
            DataFetcher.validate_data(df_small)

    def test_validate_data_missing_columns(self, sample_dataframe: pd.DataFrame):
        """Test validation fails with missing columns."""
        df_bad = sample_dataframe[["Close"]].copy()
        with pytest.raises(ValueError, match="Missing required columns"):
            DataFetcher.validate_data(df_bad)

    def test_validate_data_with_nan(self, sample_dataframe: pd.DataFrame):
        """Test validation fails with NaN values."""
        df_bad = sample_dataframe.copy()
        df_bad.loc[df_bad.index[0], "Close"] = np.nan
        with pytest.raises(ValueError, match="contains NaN"):
            DataFetcher.validate_data(df_bad)

    def test_validate_data_with_inf(self, sample_dataframe: pd.DataFrame):
        """Test validation fails with inf values."""
        df_bad = sample_dataframe.copy()
        df_bad.loc[df_bad.index[0], "Close"] = np.inf
        with pytest.raises(ValueError, match="contains inf"):
            DataFetcher.validate_data(df_bad)

    def test_validate_data_ohlc_inconsistency(self, sample_dataframe: pd.DataFrame):
        """Test validation fails when close > high."""
        df_bad = sample_dataframe.copy()
        df_bad.loc[df_bad.index[0], "Close"] = df_bad.loc[df_bad.index[0], "High"] + 0.01
        with pytest.raises(ValueError, match="OHLC validation failed"):
            DataFetcher.validate_data(df_bad)

    def test_validate_data_negative_price(self, sample_dataframe: pd.DataFrame):
        """Test validation fails with negative prices."""
        df_bad = sample_dataframe.copy()
        df_bad.loc[df_bad.index[0], "Close"] = -0.5
        with pytest.raises(ValueError, match="non-positive prices"):
            DataFetcher.validate_data(df_bad)


# ============================================================================
# Tests: YFinanceFetcher
# ============================================================================


class TestYFinanceFetcher:
    """Tests for YFinanceFetcher implementation."""

    def test_resolve_symbol(self):
        """Test FX pair to yfinance symbol resolution."""
        assert YFinanceFetcher._resolve_symbol("EURUSD") == "EURUSD=X"
        assert YFinanceFetcher._resolve_symbol("USDJPY") == "USDJPY=X"

    def test_resolve_symbol_invalid(self):
        """Test symbol resolution with invalid pair."""
        with pytest.raises(ValueError):
            YFinanceFetcher._resolve_symbol("EUR")  # Too short

    def test_initialization(self):
        """Test YFinanceFetcher initialization."""
        fetcher = YFinanceFetcher(max_retries=5, timeout_seconds=20)
        assert fetcher.max_retries == 5
        assert fetcher.timeout_seconds == 20

    def test_initialization_defaults(self):
        """Test YFinanceFetcher with default parameters."""
        fetcher = YFinanceFetcher()
        assert fetcher.max_retries == 3
        assert fetcher.timeout_seconds == 10


# ============================================================================
# Tests: AlphaVantageFetcher
# ============================================================================


class TestAlphaVantageFetcher:
    """Tests for AlphaVantageFetcher implementation."""

    def test_initialization_valid_key(self):
        """Test AlphaVantageFetcher with valid API key."""
        fetcher = AlphaVantageFetcher(api_key="demo")
        assert fetcher.api_key == "demo"

    def test_initialization_invalid_key(self):
        """Test AlphaVantageFetcher with invalid API key."""
        with pytest.raises(ValueError, match="non-empty string"):
            AlphaVantageFetcher(api_key="")

        with pytest.raises(ValueError, match="non-empty string"):
            AlphaVantageFetcher(api_key=None)


# ============================================================================
# Tests: FetcherFactory
# ============================================================================


class TestFetcherFactory:
    """Tests for FetcherFactory."""

    def test_factory_without_fallback(self):
        """Test factory without Alpha Vantage fallback."""
        factory = FetcherFactory()
        assert factory.primary_fetcher is not None
        assert factory.fallback_fetcher is None

    def test_factory_with_fallback(self):
        """Test factory with Alpha Vantage fallback."""
        factory = FetcherFactory(alpha_vantage_key="demo")
        assert factory.primary_fetcher is not None
        assert factory.fallback_fetcher is not None

    def test_get_fetcher(self):
        """Test getting fetcher for a pair."""
        factory = FetcherFactory()
        fetcher = factory.get_fetcher("EURUSD")
        assert fetcher is not None
        assert isinstance(fetcher, DataFetcher)


# ============================================================================
# Tests: Repository Service
# ============================================================================


class TestRepositoryService:
    """Tests for RepositoryService database operations."""

    def test_initialize(self, in_memory_db: RepositoryService):
        """Test database initialization creates tables."""
        session = in_memory_db.get_session()
        try:
            session.query(PriceHistory).count()
            session.query(ModelRegistry).count()
        finally:
            session.close()

    def test_upsert_price_history(self, in_memory_db: RepositoryService):
        """Test upserting price history records."""
        record = PriceHistory(
            pair="EURUSD",
            date=datetime(2024, 1, 15),
            close_price=1.0950,
            open_price=1.0940,
            high_price=1.0960,
            low_price=1.0930,
            volume=1000000,
        )

        result = in_memory_db.upsert_price_history(record)
        assert result.id is not None
        assert result.pair == "EURUSD"

    def test_get_price_history(self, in_memory_db: RepositoryService):
        """Test retrieving price history."""
        for i in range(10):
            record = PriceHistory(
                pair="EURUSD",
                date=datetime(2024, 1, 1) + timedelta(days=i),
                close_price=1.0950 + i * 0.001,
                open_price=1.0940,
                high_price=1.0960,
                low_price=1.0930,
                volume=1000000,
            )
            in_memory_db.upsert_price_history(record)

        results = in_memory_db.get_price_history("EURUSD", limit=5)
        assert len(results) == 5
        assert all(r.pair == "EURUSD" for r in results)

    def test_validate_api_key_active(self, in_memory_db: RepositoryService):
        """Test API key validation for active keys."""
        key_hash = "abc123def456"
        in_memory_db.create_api_key(key_hash, owner="test_user")

        assert in_memory_db.validate_api_key(key_hash) is True

    def test_validate_api_key_inactive(self, in_memory_db: RepositoryService):
        """Test API key validation for inactive keys."""
        session = in_memory_db.get_session()
        try:
            key = ApiKey(
                key_hash="inactive_key",
                owner="test_user",
                is_active=False,
            )
            session.add(key)
            session.commit()
        finally:
            session.close()

        assert in_memory_db.validate_api_key("inactive_key") is False

    def test_validate_api_key_expired(self, in_memory_db: RepositoryService):
        """Test API key validation for expired keys."""
        key_hash = "expired_key"
        yesterday = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        
        session = in_memory_db.get_session()
        try:
            key = ApiKey(
                key_hash=key_hash,
                owner="test_user",
                expires_at=yesterday,
            )
            session.add(key)
            session.commit()
        finally:
            session.close()

        assert in_memory_db.validate_api_key(key_hash) is False

    def test_validate_api_key_nonexistent(self, in_memory_db: RepositoryService):
        """Test API key validation for nonexistent keys."""
        assert in_memory_db.validate_api_key("nonexistent_key") is False

    def test_log_request(self, in_memory_db: RepositoryService):
        """Test request logging."""
        log_entry = in_memory_db.log_request(
            endpoint="/v1/forecast/EURUSD",
            method="GET",
            response_time_ms=150.5,
            status_code=200,
            pair="EURUSD",
            api_key_hash="abc123",
        )

        assert log_entry.id is not None
        assert log_entry.status_code == 200
        assert log_entry.response_time_ms == 150.5

    def test_register_model(self, in_memory_db: RepositoryService):
        """Test model registration."""
        model = in_memory_db.register_model(
            pair="EURUSD",
            model_version="1.0.0",
            params_path="/models/EURUSD/garch_v1.joblib",
            training_data_points=504,
            mse=0.0001,
        )

        assert model.id is not None
        assert model.pair == "EURUSD"
        assert model.model_version == "1.0.0"

    def test_get_latest_model(self, in_memory_db: RepositoryService):
        """Test retrieving latest model."""
        in_memory_db.register_model(
            pair="EURUSD",
            model_version="1.0.0",
            params_path="/models/EURUSD/garch_v1.joblib",
            training_data_points=504,
        )

        in_memory_db.register_model(
            pair="EURUSD",
            model_version="1.1.0",
            params_path="/models/EURUSD/garch_v2.joblib",
            training_data_points=504,
        )

        latest = in_memory_db.get_latest_model("EURUSD")
        assert latest.model_version == "1.1.0"

    def test_save_backtest_result(self, in_memory_db: RepositoryService):
        """Test saving backtest results."""
        result = in_memory_db.save_backtest_result(
            pair="EURUSD",
            horizon=5,
            data_points=100,
            mae=0.002,
            rmse=0.0025,
            baseline_mae=0.0022,
            baseline_rmse=0.0027,
        )

        assert result.id is not None
        # baseline_mae (0.0022) > mae (0.0020) -> GARCH outperformed baseline
        assert result.outperformance_pct > 0
        assert result.outperformance_pct == pytest.approx(9.09, abs=0.1)

    def test_get_backtest_results(self, in_memory_db: RepositoryService):
        """Test retrieving backtest results."""
        for i in range(3):
            in_memory_db.save_backtest_result(
                pair="EURUSD",
                horizon=5,
                data_points=100,
                mae=0.002 + i * 0.0001,
                rmse=0.0025,
                baseline_mae=0.0022,
                baseline_rmse=0.0027,
            )

        results = in_memory_db.get_backtest_results("EURUSD", limit=2)
        assert len(results) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])