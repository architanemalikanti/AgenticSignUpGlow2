"""
JWT token utilities for authentication.
Handles generation and validation of access and refresh tokens.
"""
import jwt
import os
from datetime import datetime, timedelta
from typing import Dict, Tuple
import logging

logger = logging.getLogger(__name__)

# Get JWT secret from environment (fallback for development)
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

# Token expiration times
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30 days


def create_access_token(user_id: str) -> str:
    """
    Create a JWT access token for a user.

    Args:
        user_id: The user's ID from the database

    Returns:
        str: Encoded JWT access token
    """
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "user_id": user_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"🔑 Created access token for user {user_id}")
    return token


def create_refresh_token(user_id: str) -> str:
    """
    Create a JWT refresh token for a user.

    Args:
        user_id: The user's ID from the database

    Returns:
        str: Encoded JWT refresh token
    """
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "user_id": user_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"🔑 Created refresh token for user {user_id}")
    return token


def create_token_pair(user_id: str) -> Tuple[str, str]:
    """
    Create both access and refresh tokens for a user.

    Args:
        user_id: The user's ID from the database

    Returns:
        Tuple[str, str]: (access_token, refresh_token)
    """
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)
    return access_token, refresh_token


def verify_token(token: str, token_type: str = "access") -> Dict:
    """
    Verify and decode a JWT token.

    Args:
        token: The JWT token to verify
        token_type: Expected token type ("access" or "refresh")

    Returns:
        Dict: Decoded token payload if valid

    Raises:
        jwt.ExpiredSignatureError: If token is expired
        jwt.InvalidTokenError: If token is invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        # Verify token type
        if payload.get("type") != token_type:
            raise jwt.InvalidTokenError(f"Expected {token_type} token, got {payload.get('type')}")

        return payload

    except jwt.ExpiredSignatureError:
        logger.warning(f"Token expired: {token[:20]}...")
        raise
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {str(e)}")
        raise
