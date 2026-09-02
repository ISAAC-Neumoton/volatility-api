"""Dependency injection for API endpoints"""

from fastapi import HTTPException, Header, status

from src.volatility_api.config import settings


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """
    Verify API key from request header.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        API key if valid

    Raises:
        HTTPException: If API key is invalid
    """
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return x_api_key
