import base64
import hashlib
import warnings
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.settings import get_settings


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


@lru_cache
def _fernet() -> Fernet:
    configured = get_settings().app_secret_key
    if not configured:
        warnings.warn(
            "Warning: APP_SECRET_KEY is not configured. Generated temporary key for development only.",
            RuntimeWarning,
            stacklevel=2,
        )
        configured = "development-only-temporary-ybt-secret"
    digest = hashlib.sha256(configured.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
