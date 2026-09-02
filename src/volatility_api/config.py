"""
Configuration module providing environment-driven settings for VolaCast.

All configuration is sourced from environment variables via Pydantic v2
BaseSettings. No secrets, API keys, or endpoints are hardcoded. This module
validates configuration at startup and ensures all required fields are set
before the application initializes.

Attributes:
    settings (Settings): Global singleton configuration instance.

Example:
    >>> from src.volatility_api.config import settings
    >>> print(settings.app_name)
    'VolaCast'
    >>> print(settings.database_url)
    'sqlite:///./volatility.db'
"""

from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application configuration model with validation.

    All fields are loaded from environment variables. Required fields without
    defaults will raise a validation error if not provided at runtime.

    Attributes:
        app_name: Display name for the application (default: 'VolaCast').
        debug: Enable debug mode for development (default: False).
        log_level: Logging verbosity level (default: 'INFO').
        database_url: SQLAlchemy database connection string.
        admin_secret_key: Secret key for admin endpoints (must be set).
        default_cache_hours: TTL for cached forecasts in hours (default: 6).
        sentry_dsn: Sentry DSN for error tracking (optional).
        max_forecast_horizon: Maximum forecast horizon in days (default: 10).
        min_data_points: Minimum historical data points required (default: 504).
        max_api_key_age_days: Maximum API key age before expiry (default: 365).
    """

    app_name: str = Field(
        default="VolaCast",
        description="Application name",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    database_url: str = Field(
        default="sqlite:///./volatility.db",
        description="SQLAlchemy database connection URL",
    )
    admin_secret_key: str = Field(
        description="Secret key for admin operations (required)",
    )
    default_cache_hours: int = Field(
        default=6,
        description="Cache TTL for forecasts in hours",
        ge=1,
        le=168,
    )
    sentry_dsn: Optional[str] = Field(
        default=None,
        description="Sentry error tracking DSN (optional)",
    )
    max_forecast_horizon: int = Field(
        default=10,
        description="Maximum forecast horizon in days",
        ge=1,
        le=90,
    )
    min_data_points: int = Field(
        default=504,
        description="Minimum historical data points (approximately 2 years daily)",
        ge=100,
        le=10000,
    )
    max_api_key_age_days: int = Field(
        default=365,
        description="Maximum age of API keys before expiry",
        ge=30,
        le=1095,
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level against standard Python logging levels."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL is valid for supported backends."""
        if not v or not any(
            v.startswith(prefix) for prefix in ("sqlite://", "postgresql://", "mysql://")
        ):
            raise ValueError(
                "DATABASE_URL must start with 'sqlite://', 'postgresql://', or 'mysql://'"
            )
        return v

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
"""Global singleton configuration instance."""

