"""
Pydantic v2 models for API request/response validation.

This module defines all data models for VolaCast, including FX pair formats,
forecast horizons, and structured error responses. All models include custom
validators to enforce domain constraints at schema validation time.

Classes:
    CurrencyPair: Validated FX pair (e.g., EURUSD, USDJPY).
    ForecastRequest: Forecast API request parameters.
    ForecastResult: Volatility forecast response.
    BacktestMetrics: Historical backtest performance data.
    HealthStatus: Application health check response.
    ErrorResponse: Structured error response.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# Supported currency pairs
SUPPORTED_PAIRS = {
    "EURUSD",
    "USDJPY",
    "GBPUSD",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "SGDUSD",
    "HKDUSD",
    "NOKDUS",
    "SEKUSD",
    "DKDUSD",
    "USDPLN",
    "USDCNY",
    "USDINR",
    "USDZAR",
    "USDNGN",
    "USDBRL",
    "USDTRY",
    "USDRUB",
    "EURCAD",
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "EURAUD",
    "EURNZD",
    "GBPJPY",
    "GBPCHF",
    "GBPAUD",
    "AUDJPY",
    "CADJPY",
    "CHFJPY",
}


class CurrencyPair(BaseModel):
    """
    Validated FX currency pair model.

    Represents a major or emerging market FX pair in 6-character format
    (e.g., EURUSD, USDJPY). The pair must be from the supported list.

    Attributes:
        pair: FX pair code (6 characters, uppercase).
        base: Base currency (3 chars).
        quote: Quote currency (3 chars).

    Example:
        >>> pair = CurrencyPair(pair="EURUSD")
        >>> pair.base
        'EUR'
        >>> pair.quote
        'USD'
    """

    pair: str = Field(..., description="FX pair in format XXXYYY (e.g., EURUSD)")

    @field_validator("pair")
    @classmethod
    def validate_pair_format(cls, v: str) -> str:
        """Validate FX pair format and supported list."""
        v_upper = v.upper().strip()
        if len(v_upper) != 6:
            raise ValueError(f"Pair must be exactly 6 characters (got '{v_upper}')")
        if not v_upper.isalpha():
            raise ValueError(f"Pair must be alphabetic (got '{v_upper}')")
        if v_upper not in SUPPORTED_PAIRS:
            raise ValueError(
                f"Pair '{v_upper}' not supported. Supported pairs: {', '.join(sorted(SUPPORTED_PAIRS))}"
            )
        return v_upper

    @property
    def base(self) -> str:
        """Get base currency (first 3 chars)."""
        return self.pair[:3]

    @property
    def quote(self) -> str:
        """Get quote currency (last 3 chars)."""
        return self.pair[3:]


class ForecastRequest(BaseModel):
    """
    Request model for volatility forecast endpoint.

    The client specifies the FX pair and forecast horizon. The API will return
    volatility forecasts and confidence intervals for the requested period.

    Attributes:
        pair: FX currency pair (e.g., EURUSD).
        horizon: Number of days to forecast (1-10 days).

    Example:
        >>> request = ForecastRequest(pair="EURUSD", horizon=5)
        >>> request.pair
        'EURUSD'
    """

    pair: str = Field(..., description="FX pair code (e.g., EURUSD)")
    horizon: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Forecast horizon in days (1-10)",
    )

    @field_validator("pair")
    @classmethod
    def validate_pair(cls, v: str) -> str:
        """Validate pair format using CurrencyPair model."""
        return CurrencyPair(pair=v).pair


class ConfidenceInterval(BaseModel):
    """
    Confidence interval bounds for volatility forecast.

    Represents parametric confidence bounds (typically 95%) for the volatility
    forecast, derived from the GARCH model's assumed distribution.

    Attributes:
        lower: Lower bound of confidence interval.
        upper: Upper bound of confidence interval.
        confidence_level: Confidence level as percentage (e.g., 95.0).

    Example:
        >>> ci = ConfidenceInterval(lower=0.20, upper=0.35, confidence_level=95.0)
        >>> ci.width
        0.15
    """

    lower: float = Field(..., ge=0.0, description="Lower confidence bound")
    upper: float = Field(..., ge=0.0, description="Upper confidence bound")
    confidence_level: float = Field(
        default=95.0,
        ge=50.0,
        le=99.9,
        description="Confidence level as percentage",
    )

    @property
    def width(self) -> float:
        """Calculate interval width."""
        return self.upper - self.lower


class ForecastResult(BaseModel):
    """
    Volatility forecast response model.

    Contains the forecasted volatility for each day in the requested horizon,
    confidence intervals, model metadata, and timestamp.

    Attributes:
        pair: FX currency pair.
        horizon: Number of forecasted days.
        forecasts: List of daily volatility forecasts.
        confidence_intervals: Confidence bounds for each day.
        model_version: Semantic version of the model used.
        generated_at: UTC timestamp when forecast was generated.
        valid_until: UTC timestamp when forecast cache expires.

    Example:
        >>> from datetime import datetime, timedelta
        >>> result = ForecastResult(
        ...     pair="EURUSD",
        ...     horizon=5,
        ...     forecasts=[0.25, 0.26, 0.27, 0.26, 0.25],
        ...     confidence_intervals=[
        ...         ConfidenceInterval(lower=0.20, upper=0.30),
        ...         ConfidenceInterval(lower=0.21, upper=0.31),
        ...         # ... more intervals
        ...     ],
        ...     model_version="1.0.0",
        ... )
    """

    pair: str = Field(..., description="FX pair")
    horizon: int = Field(..., ge=1, le=10, description="Forecast horizon in days")
    forecasts: list[float] = Field(
        ...,
        description="Daily volatility forecasts (one per day)",
    )
    confidence_intervals: list[ConfidenceInterval] = Field(
        ...,
        description="Confidence intervals for each forecast day",
    )
    model_version: str = Field(..., description="Model version (semantic versioning)")
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Forecast generation timestamp (UTC)",
    )
    valid_until: datetime = Field(
        ...,
        description="Cache expiry timestamp (UTC)",
    )

    @field_validator("forecasts")
    @classmethod
    def validate_forecasts_length(cls, v: list[float], info) -> list[float]:
        """Ensure forecasts match horizon length."""
        horizon = info.data.get("horizon")
        if horizon and len(v) != horizon:
            raise ValueError(f"Forecasts length {len(v)} must match horizon {horizon}")
        if not all(isinstance(f, (int, float)) and f >= 0 for f in v):
            raise ValueError("All forecasts must be non-negative numbers")
        return v

    @field_validator("confidence_intervals")
    @classmethod
    def validate_intervals_length(cls, v: list[ConfidenceInterval], info) -> list[ConfidenceInterval]:
        """Ensure intervals match horizon length."""
        horizon = info.data.get("horizon")
        if horizon and len(v) != horizon:
            raise ValueError(f"Intervals length {len(v)} must match horizon {horizon}")
        return v


class BacktestMetrics(BaseModel):
    """
    Historical backtesting performance metrics.

    Represents out-of-sample performance of the GARCH model against a naive
    rolling-window baseline, with no lookahead bias.

    Attributes:
        pair: FX currency pair.
        mae: Mean Absolute Error of model forecasts.
        rmse: Root Mean Squared Error of model forecasts.
        baseline_mae: Baseline MAE (rolling std deviation model).
        baseline_rmse: Baseline RMSE (rolling std deviation model).
        outperformance_pct: Outperformance percentage vs baseline.
        run_date: Date when backtest was run.
        data_points: Number of out-of-sample predictions evaluated.

    Example:
        >>> metrics = BacktestMetrics(
        ...     pair="EURUSD",
        ...     mae=0.002,
        ...     rmse=0.0025,
        ...     baseline_mae=0.0022,
        ...     baseline_rmse=0.0027,
        ...     outperformance_pct=-9.1,
        ... )
    """

    pair: str = Field(..., description="FX pair")
    mae: float = Field(..., ge=0.0, description="Model Mean Absolute Error")
    rmse: float = Field(..., ge=0.0, description="Model Root Mean Squared Error")
    baseline_mae: float = Field(..., ge=0.0, description="Baseline MAE")
    baseline_rmse: float = Field(..., ge=0.0, description="Baseline RMSE")
    outperformance_pct: float = Field(
        ...,
        description="Outperformance percentage (positive = better than baseline)",
    )
    run_date: datetime = Field(..., description="Backtest run date")
    data_points: int = Field(..., ge=1, description="Number of OOS predictions")


class HealthStatus(BaseModel):
    """
    Application health check response.

    Indicates the overall health of the VolaCast service, including database
    connectivity, data freshness, and free disk space.

    Attributes:
        status: Overall status ('healthy', 'degraded', 'unhealthy').
        database_connected: Database connectivity status.
        data_fresh: Whether price data is recent (< 1 day old).
        disk_free_mb: Free disk space in MB (ephemeral storage).
        timestamp: Health check timestamp.

    Example:
        >>> health = HealthStatus(
        ...     status="healthy",
        ...     database_connected=True,
        ...     data_fresh=True,
        ...     disk_free_mb=256,
        ... )
    """

    status: str = Field(
        ...,
        pattern="^(healthy|degraded|unhealthy)$",
        description="Overall service status",
    )
    database_connected: bool = Field(..., description="Database connectivity")
    data_fresh: bool = Field(..., description="Price data recency")
    disk_free_mb: float = Field(..., ge=0.0, description="Free disk space in MB")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Health check timestamp",
    )


class ErrorResponse(BaseModel):
    """
    Structured error response for API errors.

    All errors returned by VolaCast follow this standardized format for
    consistency and easy client-side handling.

    Attributes:
        error_code: Machine-readable error code (e.g., 'PAIR_NOT_SUPPORTED').
        message: Human-readable error message.
        detail: Optional additional details about the error.
        timestamp: Error timestamp.

    Example:
        >>> error = ErrorResponse(
        ...     error_code="INVALID_HORIZON",
        ...     message="Forecast horizon must be 1-10 days",
        ...     detail="Received horizon=15",
        ... )
    """

    error_code: str = Field(
        ...,
        description="Machine-readable error code",
    )
    message: str = Field(..., description="Human-readable error message")
    detail: Optional[str] = Field(
        default=None,
        description="Additional error details",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Error timestamp",
    )

