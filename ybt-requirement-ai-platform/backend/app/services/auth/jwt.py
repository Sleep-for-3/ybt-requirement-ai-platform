import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.settings import get_settings


class TokenError(ValueError):
    pass


def create_token(user_id: int, token_type: str, expires_delta: timedelta, jti: str | None = None) -> tuple[str, dict[str, Any]]:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": token_type,
        "jti": jti or uuid.uuid4().hex,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(claims, _secret(), algorithm="HS256"), claims


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"], options={"require": ["sub", "type", "jti", "exp"]})
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    if expected_type and claims.get("type") != expected_type:
        raise TokenError("Invalid token type")
    return claims


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secret() -> str:
    settings = get_settings()
    secret = settings.jwt_secret_key or settings.app_secret_key
    if not secret:
        if settings.environment.lower() == "production":
            raise RuntimeError("JWT_SECRET_KEY must be configured in production")
        secret = "development-only-generated-token-signing-key"
    return secret
