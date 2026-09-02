"""
Structured logging module for VolaCast.

Configures application-wide JSON logging and request tracing to monitor
performance, latency (<= 2s p95 target), and error tracking.
"""

import json
import logging
import sys
import time
from typing import Any, Dict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from volatility_api.config import settings
from volatility_api.data.repository import RepositoryService


class JSONFormatter(logging.Formatter):
    """Formats log records into standard JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_payload.update(record.extra_data)
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_payload)


def setup_logging() -> logging.Logger:
    """Initialize root logger with JSON handler and configured log level."""
    logger = logging.getLogger(settings.app_name)
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = setup_logging()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that calculates request duration, logs JSON metrics,
    and records audit logs to the SQLite repository.
    """

    def __init__(self, app, repo_service: RepositoryService):
        super().__init__(app)
        self.repo = repo_service

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.perf_counter()
        raw_key = request.headers.get("X-API-Key")
        api_key_hash = None

        if raw_key:
            from volatility_api.core.security import SecurityService
            try:
                api_key_hash = SecurityService.hash_api_key(raw_key)
            except ValueError:
                api_key_hash = None

        response: Optional[Response] = None
        status_code = 500
        error_code = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_code = exc.__class__.__name__
            raise exc
        finally:
            process_time_ms = (time.perf_counter() - start_time) * 1000.0
            pair = request.path_params.get("pair")

            logger.info(
                f"{request.method} {request.url.path} completed with {status_code}",
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": round(process_time_ms, 2),
                        "pair": pair,
                    }
                },
            )

            # Audit log to DB (ignore health check to prevent log bloat)
            if request.url.path != "/v1/health":
                try:
                    self.repo.log_request(
                        endpoint=request.url.path,
                        method=request.method,
                        response_time_ms=process_time_ms,
                        status_code=status_code,
                        pair=pair,
                        api_key_hash=api_key_hash,
                        error_code=error_code,
                    )
                except Exception as log_err:
                    logger.error(f"Failed to record audit log: {log_err}")