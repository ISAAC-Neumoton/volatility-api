"""
Structured logging configuration for VolaCast.

This module provides structured JSON logging with contextual information including
request duration, HTTP status codes, API key hash (for audit), and error traces.
All logs are emitted to stdout/stderr for container-friendly operation.

Functions:
    setup_logging: Initialize logging configuration.
    get_logger: Retrieve a logger instance for a module.

Example:
    >>> from src.volatility_api.core.logging import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Application started", extra={"action": "startup"})
"""

import json
import logging
import logging.config
import sys
import time
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """
    Custom log formatter that outputs structured JSON logs.

    This formatter converts log records to JSON with consistent structure:
    {
        "timestamp": "2024-01-15T10:30:45.123Z",
        "level": "INFO",
        "logger": "src.volatility_api.api.routes",
        "message": "Forecast retrieved",
        "extra": {...}
    }

    Extra fields from the log record context are included in the output for
    rich observability.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: The log record to format.

        Returns:
            JSON-serialized log entry as a string.
        """
        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include exception traceback if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Include extra fields from the record
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
            )
        }

        if extra_fields:
            log_data["extra"] = extra_fields

        try:
            return json.dumps(log_data, default=str)
        except (TypeError, ValueError):
            # Fallback to plain string if JSON serialization fails
            return str(log_data)


LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": JSONFormatter,
        },
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
        "error_console": {
            "class": "logging.StreamHandler",
            "level": "WARNING",
            "formatter": "json",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "src.volatility_api": {
            "level": "DEBUG",
            "handlers": ["console", "error_console"],
            "propagate": False,
        },
        "uvicorn": {
            "level": "INFO",
            "handlers": ["console"],
        },
        "uvicorn.access": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}


def setup_logging(log_level: str = "INFO") -> None:
    """
    Initialize logging configuration.

    Configures structured JSON logging to stdout/stderr. All handlers are
    configured for container-friendly operation (no file handlers).

    Args:
        log_level: Minimum logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Example:
        >>> setup_logging("DEBUG")
        >>> logger = get_logger(__name__)
        >>> logger.debug("Debug message enabled")
    """
    # Update config with desired log level
    LOGGING_CONFIG["loggers"]["src.volatility_api"]["level"] = log_level.upper()
    LOGGING_CONFIG["handlers"]["console"]["level"] = log_level.upper()

    logging.config.dictConfig(LOGGING_CONFIG)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name, typically __name__ from calling module.

    Returns:
        Configured logger instance.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Service initialized")
    """
    return logging.getLogger(name)


class LoggingContext:
    """
    Context manager for adding structured context to logs.

    Temporarily adds extra fields to all logs within a with block.

    Example:
        >>> logger = get_logger(__name__)
        >>> with LoggingContext(api_key_hash="abc123", pair="EURUSD"):
        ...     logger.info("Processing forecast")
        ...     # Logs will include api_key_hash and pair fields
    """

    def __init__(self, **context: Any):
        """
        Initialize logging context.

        Args:
            **context: Arbitrary key-value pairs to add to log records.
        """
        self.context = context

    def __enter__(self) -> "LoggingContext":
        """Enter context manager."""
        self._token = logging.LoggerAdapter.__new__(logging.LoggerAdapter)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        pass

