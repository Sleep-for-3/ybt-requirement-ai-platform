import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import LoginAttempt, RefreshToken, User
from app.services.auth.jwt import TokenError, create_token, decode_token, token_digest
from app.services.auth.password import hash_password, verify_password


_DUMMY_HASH = hash_password("nonexistent-user-dummy-password")


class AuthenticationError(ValueError):
    pass


def authenticate(db: Session, username: str, password: str) -> User:
    normalized = username.strip().lower()
    attempt = _attempt(db, normalized)
    now = datetime.now(UTC)
    if attempt.locked_until and _aware(attempt.locked_until) > now:
        raise AuthenticationError("Invalid username or password")
    user = db.scalar(select(User).where(User.username == normalized))
    password_hash = user.password_hash if user and user.password_hash else _DUMMY_HASH
    valid = verify_password(password, password_hash)
    if not user or not valid or user.status != "active":
        attempt.failed_count += 1
        attempt.last_attempt_at = now
        if attempt.failed_count >= get_settings().login_max_failures:
            attempt.locked_until = now + timedelta(seconds=get_settings().login_lock_seconds)
        db.commit()
        raise AuthenticationError("Invalid username or password")
    attempt.failed_count = 0
    attempt.locked_until = None
    attempt.last_attempt_at = now
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    db.refresh(user)
    return user


def create_session(db: Session, user: User, *, commit: bool = True) -> dict[str, object]:
    """Issue an access/refresh pair.

    ``commit=False`` flushes the refresh row inside the caller's transaction so a rotation can
    revoke the old token and issue the replacement atomically (W02/B05).
    """

    settings = get_settings()
    access, _ = create_token(user.id, "access", timedelta(minutes=settings.access_token_minutes))
    refresh_lifetime = timedelta(days=settings.refresh_token_days)
    refresh, claims = create_token(user.id, "refresh", refresh_lifetime)
    db.add(RefreshToken(
        user_id=user.id,
        token_jti=claims["jti"],
        token_hash=token_digest(refresh),
        expires_at=datetime.now(UTC) + refresh_lifetime,
    ))
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
    }

def rotate_refresh_token(db: Session, refresh_token: str) -> dict[str, object]:
    """Rotate a refresh token exactly once, atomically.

    The old token is claimed with a single conditional UPDATE, so of N concurrent requests
    carrying the same refresh token only one wins (the others see rowcount 0 and are rejected).
    Revoking the old token and issuing the replacement happen in the same transaction; there is
    no commit boundary in between that a concurrent request could observe.
    """

    try:
        claims = decode_token(refresh_token, "refresh")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc
    jti = str(claims["jti"])
    digest = token_digest(refresh_token)
    now = datetime.now(UTC)

    claimed = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_jti == jti,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.token_hash == digest,
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.rollback()
        # Unknown, already consumed (replay) or tampered token: one indistinguishable error.
        raise AuthenticationError("Refresh token is revoked")

    record = db.scalar(select(RefreshToken).where(RefreshToken.token_jti == jti))
    if record is None:  # pragma: no cover - the claim above guarantees the row
        db.rollback()
        raise AuthenticationError("Refresh token is revoked")
    if _aware(record.expires_at) <= now:
        db.rollback()
        raise AuthenticationError("Refresh token is expired")
    user = db.get(User, int(claims["sub"]))
    if not user or user.status != "active":
        db.rollback()
        raise AuthenticationError("User is disabled")

    try:
        replacement = create_session(db, user, commit=False)
        replacement_claims = decode_token(str(replacement["refresh_token"]), "refresh")
        record.replaced_by_jti = replacement_claims["jti"]
        db.commit()
    except Exception:
        # Issuing the replacement failed: roll the whole rotation back so the old token is not
        # consumed and no partial replacement is left active.
        db.rollback()
        raise
    return replacement


def revoke_refresh_token(db: Session, refresh_token: str) -> int | None:
    try:
        claims = decode_token(refresh_token, "refresh")
    except TokenError:
        return None
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_jti == claims["jti"]))
    if record and not record.revoked_at:
        record.revoked_at = datetime.now(UTC)
        db.commit()
    return record.user_id if record else None


def user_from_access_token(db: Session, token: str) -> User:
    try:
        claims = decode_token(token, "access")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc
    user = db.get(User, int(claims["sub"]))
    if not user or user.status != "active":
        raise AuthenticationError("User is disabled")
    return user


def _attempt(db: Session, username: str) -> LoginAttempt:
    identifier_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
    attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.identifier_hash == identifier_hash))
    if attempt is None:
        attempt = LoginAttempt(identifier_hash=identifier_hash)
        db.add(attempt)
        db.flush()
    return attempt


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
