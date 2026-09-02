"""
FastAPI dependency injection module.

Provides shared dependencies for database sessions, repository access,
and API key authentication checks.
"""

from typing import Generator
from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from volatility_api.config import settings
from volatility_api.core.security import SecurityService
from volatility_api.data.repository import RepositoryService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
admin_key_header = APIKeyHeader(name="X-Admin-Secret", auto_error=False)

# Shared repository singleton instance
repository = RepositoryService(settings.database_url)


def get_repository() -> RepositoryService:
    """Dependency that returns the RepositoryService instance."""
    return repository


async def verify_api_key(
    api_key: str = Security(api_key_header),
    repo: RepositoryService = Security(get_repository),
) -> str:
    """
    Authenticate consumer requests via the X-API-Key header.

    Raises:
        HTTPException: 401 Unauthorized if missing, invalid, or expired.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "MISSING_API_KEY",
                "message": "X-API-Key header is missing.",
            },
        )

    key_hash = SecurityService.hash_api_key(api_key)
    is_valid = repo.validate_api_key(key_hash)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_API_KEY",
                "message": "The provided API key is invalid, revoked, or expired.",
            },
        )

    return key_hash


async def verify_admin_key(
    admin_key: str = Security(admin_key_header),
) -> bool:
    """
    Validate administrative access using the X-Admin-Secret header.

    Raises:
        HTTPException: 403 Forbidden if secret key does not match.
    """
    if not admin_key or admin_key != settings.admin_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "FORBIDDEN",
                "message": "Administrative privileges required.",
            },
        )
    return True