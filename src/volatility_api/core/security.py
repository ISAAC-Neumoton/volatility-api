"""
Security utilities for API key management and cryptographic operations.

This module provides cryptographic services for hashing API keys, verifying
credentials, and generating new API keys. All operations use SHA-256 hashing
with optional salt derivation for production deployments.

Classes:
    SecurityService: Singleton service for all security operations.
"""

import hashlib
import secrets
from typing import Optional


class SecurityService:
    """
    Security service for API key management and cryptographic operations.

    All API keys are hashed using SHA-256 before persistence in the database.
    This class provides methods to generate new keys, hash keys, and verify
    raw keys against stored hashes. No plaintext keys are stored.

    Methods:
        generate_api_key: Generate a new cryptographically secure API key.
        hash_api_key: Hash an API key using SHA-256.
        verify_api_key: Verify a raw key matches a stored hash.
    """

    # Constants for API key generation
    KEY_LENGTH = 32  # 256-bit keys = 32 bytes
    KEY_PREFIX = "vca_"  # VolaCast API prefix for easy identification

    @staticmethod
    def generate_api_key() -> str:
        """
        Generate a new cryptographically secure API key.

        The generated key consists of a human-readable prefix ("vca_") followed
        by a base64-encoded 256-bit random value. This format makes it easy to
        identify VolaCast API keys in logs and headers.

        Returns:
            A new API key string in format "vca_<base64-encoded-random>".

        Example:
            >>> key = SecurityService.generate_api_key()
            >>> key.startswith("vca_")
            True
            >>> len(key) > len("vca_")
            True
        """
        random_bytes = secrets.token_bytes(SecurityService.KEY_LENGTH)
        random_b64 = secrets.token_urlsafe(SecurityService.KEY_LENGTH)
        return f"{SecurityService.KEY_PREFIX}{random_b64}"

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """
        Hash an API key using SHA-256.

        This method should be called before storing API keys in the database.
        The hash is one-way: we cannot recover the original key from the hash.
        This ensures that even if the database is compromised, the keys remain
        protected.

        Args:
            api_key: Plaintext API key to hash.

        Returns:
            Hexadecimal SHA-256 hash of the API key.

        Raises:
            ValueError: If api_key is empty or None.

        Example:
            >>> key = SecurityService.generate_api_key()
            >>> hash1 = SecurityService.hash_api_key(key)
            >>> hash2 = SecurityService.hash_api_key(key)
            >>> hash1 == hash2
            True
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("API key must be a non-empty string")

        # Use SHA-256 for consistent, fast hashing
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_api_key(raw_key: str, stored_hash: str) -> bool:
        """
        Verify that a raw API key matches a stored hash.

        This method performs a constant-time comparison to prevent timing
        attacks. It is used during authentication to validate API keys
        presented in request headers.

        Args:
            raw_key: Plaintext API key provided by the client.
            stored_hash: Stored SHA-256 hash from the database.

        Returns:
            True if the key matches the hash, False otherwise.

        Example:
            >>> key = SecurityService.generate_api_key()
            >>> hash_val = SecurityService.hash_api_key(key)
            >>> SecurityService.verify_api_key(key, hash_val)
            True
            >>> SecurityService.verify_api_key("wrong_key", hash_val)
            False
        """
        if not raw_key or not stored_hash:
            return False

        try:
            computed_hash = SecurityService.hash_api_key(raw_key)
            # Use secrets.compare_digest for constant-time comparison (timing attack resistant)
            return secrets.compare_digest(computed_hash, stored_hash)
        except (ValueError, TypeError):
            return False

