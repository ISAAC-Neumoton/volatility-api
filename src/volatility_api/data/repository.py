"""
SQLAlchemy ORM models and repository service for data persistence.

This module defines all database models using SQLAlchemy 2.0 Declarative syntax
and provides the RepositoryService class for all database operations. Models
enforce referential integrity, unique constraints, and data validation at the
database level.

Classes:
    Base: Declarative base for all ORM models.
    PriceHistory: Historical FX price data (OHLC + volume).
    ModelRegistry: Record of fitted GARCH models with serialization paths.
    ApiKey: API key records with hashed credentials.
    RequestLog: Audit log of API requests (rate limiting, analytics).
    BacktestResult: Historical backtesting performance metrics.
    RepositoryService: Singleton service for all database operations.

Example:
    >>> from src.volatility_api.data.repository import RepositoryService
    >>> repo = RepositoryService("sqlite:///volatility.db")
    >>> await repo.initialize()
    >>> price_history = await repo.get_price_history("EURUSD", limit=504)
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (
    create_engine,
    select,
    and_,
    desc,
    func,
    UniqueConstraint,
    Index,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text


class Base(DeclarativeBase):
    """
    SQLAlchemy declarative base for all ORM models.

    All model classes inherit from this Base to use SQLAlchemy's Declarative
    system for automatic table creation and relationship management.
    """

    pass


class PriceHistory(Base):
    """
    Historical FX price data model.

    Stores daily (or intraday) OHLC close prices and volume for each FX pair.
    Enforces uniqueness on (pair, date) to prevent duplicates.

    Attributes:
        id: Primary key (auto-increment).
        pair: FX pair code (e.g., EURUSD).
        date: Date timestamp (UTC).
        close_price: Closing price for the period.
        open_price: Opening price (optional).
        high_price: High price (optional).
        low_price: Low price (optional).
        volume: Trading volume (optional).
        created_at: Record creation timestamp.
    """

    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(6), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    close_price = Column(Float, nullable=False)
    open_price = Column(Float, nullable=True)
    high_price = Column(Float, nullable=True)
    low_price = Column(Float, nullable=True)
    volume = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("pair", "date", name="uq_pair_date"),
        Index("ix_pair_date", "pair", "date"),
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<PriceHistory(pair={self.pair}, date={self.date}, "
            f"close={self.close_price})>"
        )


class ModelRegistry(Base):
    """
    Registry of fitted GARCH models with serialization paths.

    Records metadata for each trained model instance, including the FX pair,
    model version, fit timestamp, and joblib serialization path.

    Attributes:
        id: Primary key (auto-increment).
        pair: FX pair the model was trained on.
        model_version: Semantic version (e.g., "1.0.0").
        fitted_at: Timestamp when model was fitted.
        params_path: Joblib file path for model serialization.
        training_data_points: Number of observations used in training.
        mse: Mean squared error on training data.
        created_at: Record creation timestamp.
    """

    __tablename__ = "model_registry"

    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(6), nullable=False, index=True)
    model_version = Column(String(20), nullable=False)
    fitted_at = Column(DateTime, nullable=False)
    params_path = Column(String(512), nullable=False, unique=True)
    training_data_points = Column(Integer, nullable=False)
    mse = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_pair_version", "pair", "model_version"),
        Index("ix_pair_latest", "pair", "fitted_at"),
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<ModelRegistry(pair={self.pair}, version={self.model_version}, "
            f"fitted={self.fitted_at})>"
        )


class ApiKey(Base):
    """
    API key records with hashed credentials.

    Stores API keys in hashed form (SHA-256) with owner and activation status.
    Provides expiry validation and audit trail.

    Attributes:
        id: Primary key (auto-increment).
        key_hash: SHA-256 hash of the API key (never store plaintext).
        owner: User/owner identifier for the key.
        is_active: Whether the key is currently valid.
        created_at: Key creation timestamp.
        expires_at: Key expiry timestamp (if set).
        last_used_at: Timestamp of last successful authentication.
        request_count: Cumulative API request count.
    """

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    owner = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)
    last_used_at = Column(DateTime, nullable=True)
    request_count = Column(Integer, default=0, nullable=False)

    def is_expired(self) -> bool:
        """Check if API key has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"<ApiKey(owner={self.owner}, active={self.is_active})>"


class RequestLog(Base):
    """
    Audit log of API requests for rate limiting and analytics.

    Records metadata about every API request including pair, timestamp,
    response time, status code, and API key hash for traceability.

    Attributes:
        id: Primary key (auto-increment).
        timestamp: Request timestamp.
        pair: FX pair requested (if applicable).
        api_key_hash: Hash of API key used (for audit).
        endpoint: API endpoint called.
        method: HTTP method (GET, POST, etc.).
        response_time_ms: Response time in milliseconds.
        status_code: HTTP response status code.
        error_code: Application error code (if error).
    """

    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    pair = Column(String(6), nullable=True, index=True)
    api_key_hash = Column(String(64), nullable=True, index=True)
    endpoint = Column(String(256), nullable=False)
    method = Column(String(10), nullable=False)
    response_time_ms = Column(Float, nullable=False)
    status_code = Column(Integer, nullable=False, index=True)
    error_code = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_timestamp_pair", "timestamp", "pair"),
        Index("ix_timestamp_key", "timestamp", "api_key_hash"),
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<RequestLog(method={self.method}, endpoint={self.endpoint}, "
            f"status={self.status_code}, time={self.response_time_ms}ms)>"
        )


class BacktestResult(Base):
    """
    Historical backtesting performance metrics.

    Records out-of-sample performance of GARCH model against naive baseline
    for audit trail and performance tracking.

    Attributes:
        id: Primary key (auto-increment).
        pair: FX pair backtested.
        run_date: Date when backtest was conducted.
        horizon: Forecast horizon in days.
        data_points: Number of out-of-sample predictions.
        mae: Model mean absolute error.
        rmse: Model root mean squared error.
        baseline_mae: Baseline (rolling std) MAE.
        baseline_rmse: Baseline (rolling std) RMSE.
        outperformance_pct: Percentage outperformance vs baseline.
        created_at: Record creation timestamp.
    """

    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(6), nullable=False, index=True)
    run_date = Column(DateTime, nullable=False)
    horizon = Column(Integer, nullable=False)
    data_points = Column(Integer, nullable=False)
    mae = Column(Float, nullable=False)
    rmse = Column(Float, nullable=False)
    baseline_mae = Column(Float, nullable=False)
    baseline_rmse = Column(Float, nullable=False)
    outperformance_pct = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_pair_date", "pair", "run_date"),
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<BacktestResult(pair={self.pair}, outperformance="
            f"{self.outperformance_pct:.1f}%)>"
        )


class RepositoryService:
    """
    Singleton service for all database operations.

    Encapsulates session management, CRUD operations, and schema initialization.
    Supports both synchronous and asynchronous access patterns depending on
    database URL scheme (sqlite vs postgresql, etc.).

    Methods:
        initialize: Create tables and initialize schema.
        get_price_history: Retrieve price data for a pair.
        upsert_price_history: Insert or update price records.
        get_latest_model: Get most recent model for a pair.
        register_model: Register a newly fitted model.
        validate_api_key: Check if API key hash is valid and active.
        create_api_key: Generate and persist a new API key hash.
        log_request: Record a request to audit log.
        get_backtest_results: Retrieve latest backtest metrics.
        save_backtest_result: Persist backtest metrics.

    Example:
        >>> repo = RepositoryService("sqlite:///./volatility.db")
        >>> await repo.initialize()
        >>> prices = await repo.get_price_history("EURUSD")
    """

    def __init__(self, database_url: str, echo: bool = False):
        """
        Initialize repository service.

        Args:
            database_url: SQLAlchemy connection string.
            echo: Enable SQL query logging (for debugging).
        """
        self.database_url = database_url
        self.echo = echo

        # Create engine
        if "sqlite://" in database_url:
            # Synchronous SQLite engine for file operations
            self.engine = create_engine(
                database_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            # For production databases, would use async
            self.engine = create_engine(database_url, echo=echo)

        # Create session factory
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    def initialize(self) -> None:
        """
        Initialize database schema.

        Creates all tables defined in Base metadata. Safe to call multiple times
        (CREATE TABLE IF NOT EXISTS is used by SQLAlchemy).

        Raises:
            Exception: If database connection fails.
        """
        Base.metadata.create_all(self.engine)

    def get_session(self) -> Session:
        """
        Get a database session.

        Returns:
            Active database session (caller responsible for cleanup).
        """
        return self.SessionLocal()

    def get_price_history(
        self,
        pair: str,
        limit: int = 504,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[PriceHistory]:
        """
        Retrieve price history for a currency pair.

        Args:
            pair: FX pair code (e.g., EURUSD).
            limit: Maximum number of records to return.
            start_date: Optional start date filter.
            end_date: Optional end date filter.

        Returns:
            List of PriceHistory records ordered by date descending.
        """
        session = self.get_session()
        try:
            query = session.query(PriceHistory).filter(PriceHistory.pair == pair)

            if start_date:
                query = query.filter(PriceHistory.date >= start_date)
            if end_date:
                query = query.filter(PriceHistory.date <= end_date)

            return (
                query.order_by(desc(PriceHistory.date))
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def upsert_price_history(self, price_record: PriceHistory) -> PriceHistory:
        """
        Insert or update a price record.

        Uses SQLAlchemy's merge method to handle both insert and update
        based on the unique constraint (pair, date).

        Args:
            price_record: PriceHistory record to upsert.

        Returns:
            Merged PriceHistory record.
        """
        session = self.get_session()
        try:
            merged = session.merge(price_record)
            session.commit()
            return merged
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_latest_model(self, pair: str) -> Optional[ModelRegistry]:
        """
        Get the most recently fitted model for a pair.

        Args:
            pair: FX pair code.

        Returns:
            Most recent ModelRegistry or None if no models exist.
        """
        session = self.get_session()
        try:
            return (
                session.query(ModelRegistry)
                .filter(ModelRegistry.pair == pair)
                .order_by(desc(ModelRegistry.fitted_at))
                .first()
            )
        finally:
            session.close()

    def register_model(
        self,
        pair: str,
        model_version: str,
        params_path: str,
        training_data_points: int,
        mse: Optional[float] = None,
    ) -> ModelRegistry:
        """
        Register a newly fitted model.

        Args:
            pair: FX pair the model was trained on.
            model_version: Semantic version string.
            params_path: Joblib serialization file path.
            training_data_points: Number of training observations.
            mse: Mean squared error on training data.

        Returns:
            Created ModelRegistry record.
        """
        session = self.get_session()
        try:
            model = ModelRegistry(
                pair=pair,
                model_version=model_version,
                fitted_at=datetime.utcnow(),
                params_path=params_path,
                training_data_points=training_data_points,
                mse=mse,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            return model
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def validate_api_key(self, key_hash: str) -> bool:
        """
        Validate if an API key hash is active and non-expired.

        Args:
            key_hash: SHA-256 hash of the API key.

        Returns:
            True if key is valid and active, False otherwise.
        """
        session = self.get_session()
        try:
            api_key = session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()

            if not api_key:
                return False

            if not api_key.is_active:
                return False

            if api_key.is_expired():
                return False

            # Update last used timestamp
            api_key.last_used_at = datetime.utcnow()
            session.commit()

            return True
        except Exception:
            return False
        finally:
            session.close()

    def create_api_key(
        self,
        key_hash: str,
        owner: str,
        expires_in_days: Optional[int] = None,
    ) -> ApiKey:
        """
        Create and persist a new API key record.

        Args:
            key_hash: SHA-256 hash of the API key.
            owner: Owner/user identifier.
            expires_in_days: Optional expiry duration in days.

        Returns:
            Created ApiKey record.
        """
        session = self.get_session()
        try:
            expires_at = None
            if expires_in_days:
                expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

            api_key = ApiKey(
                key_hash=key_hash,
                owner=owner,
                expires_at=expires_at,
            )
            session.add(api_key)
            session.commit()
            session.refresh(api_key)
            return api_key
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def log_request(
        self,
        endpoint: str,
        method: str,
        response_time_ms: float,
        status_code: int,
        pair: Optional[str] = None,
        api_key_hash: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> RequestLog:
        """
        Log an API request to audit log.

        Args:
            endpoint: API endpoint path.
            method: HTTP method.
            response_time_ms: Response time in milliseconds.
            status_code: HTTP status code.
            pair: FX pair (if applicable).
            api_key_hash: API key hash (for audit).
            error_code: Application error code (if error).

        Returns:
            Created RequestLog record.
        """
        session = self.get_session()
        try:
            log_entry = RequestLog(
                endpoint=endpoint,
                method=method,
                response_time_ms=response_time_ms,
                status_code=status_code,
                pair=pair,
                api_key_hash=api_key_hash,
                error_code=error_code,
            )
            session.add(log_entry)
            session.commit()
            session.refresh(log_entry)
            return log_entry
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def get_backtest_results(self, pair: str, limit: int = 10) -> List[BacktestResult]:
        """
        Retrieve latest backtest results for a pair.

        Args:
            pair: FX pair code.
            limit: Maximum number of records to return.

        Returns:
            List of BacktestResult ordered by run_date descending.
        """
        session = self.get_session()
        try:
            return (
                session.query(BacktestResult)
                .filter(BacktestResult.pair == pair)
                .order_by(desc(BacktestResult.run_date))
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def save_backtest_result(
        self,
        pair: str,
        horizon: int,
        data_points: int,
        mae: float,
        rmse: float,
        baseline_mae: float,
        baseline_rmse: float,
    ) -> BacktestResult:
        """
        Save backtest result metrics.

        Args:
            pair: FX pair backtested.
            horizon: Forecast horizon in days.
            data_points: Number of OOS predictions.
            mae: Model MAE.
            rmse: Model RMSE.
            baseline_mae: Baseline MAE.
            baseline_rmse: Baseline RMSE.

        Returns:
            Created BacktestResult record.
        """
        session = self.get_session()
        try:
            # Calculate outperformance percentage
            if baseline_mae > 0:
                outperformance_pct = ((baseline_mae - mae) / baseline_mae) * 100
            else:
                outperformance_pct = 0.0

            result = BacktestResult(
                pair=pair,
                run_date=datetime.utcnow(),
                horizon=horizon,
                data_points=data_points,
                mae=mae,
                rmse=rmse,
                baseline_mae=baseline_mae,
                baseline_rmse=baseline_rmse,
                outperformance_pct=outperformance_pct,
            )
            session.add(result)
            session.commit()
            session.refresh(result)
            return result
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def save_model_with_joblib(
        self,
        model: Any,
        pair: str,
        model_version: str = "1.0.0",
        training_data_points: int = 504,
    ) -> Tuple[str, ModelRegistry]:
        """
        Serialize and persist model using joblib.

        Saves model to disk and registers metadata in ModelRegistry table.

        Args:
            model: GARCHModel instance with fitted state.
            pair: FX pair the model was trained on.
            model_version: Semantic version (default "1.0.0").
            training_data_points: Number of training observations.

        Returns:
            Tuple of (file_path, ModelRegistry record).

        Raises:
            ImportError: If joblib not installed.
            IOError: If model persistence fails.
        """
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required for model serialization")

        import os

        # Create models directory if needed
        model_dir = "./models"
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        # Construct file path with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(
            model_dir,
            f"{pair}_garch_v{model_version}_{timestamp}.pkl",
        )

        # Serialize model
        try:
            joblib.dump(model, file_path, compress=3)
        except Exception as e:
            raise IOError(f"Failed to serialize model to {file_path}: {e}") from e

        # Register in database
        registry = self.register_model(
            pair=pair,
            model_version=model_version,
            params_path=file_path,
            training_data_points=training_data_points,
            mse=None,
        )

        return file_path, registry

    def load_model_with_joblib(self, file_path: str) -> Any:
        """
        Load model from joblib serialization.

        Args:
            file_path: Path to serialized model file.

        Returns:
            Deserialized model instance.

        Raises:
            ImportError: If joblib not installed.
            FileNotFoundError: If file does not exist.
            IOError: If model deserialization fails.
        """
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required for model deserialization")

        import os

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Model file not found: {file_path}")

        try:
            return joblib.load(file_path)
        except Exception as e:
            raise IOError(f"Failed to deserialize model from {file_path}: {e}") from e

    def get_latest_model_for_pair(self, pair: str) -> Optional[ModelRegistry]:
        """
        Get metadata for latest trained model for a pair.

        Args:
            pair: FX pair code.

        Returns:
            ModelRegistry record or None if no models exist.
        """
        return self.get_latest_model(pair)

    def get_latest_model_path(self, pair: str) -> Optional[str]:
        """
        Get file path to latest serialized model.

        Args:
            pair: FX pair code.

        Returns:
            File path string or None if no models exist.
        """
        model_registry = self.get_latest_model(pair)
        return model_registry.params_path if model_registry else None

