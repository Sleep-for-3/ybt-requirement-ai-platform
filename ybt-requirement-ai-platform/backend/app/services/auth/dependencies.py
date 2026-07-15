from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import get_settings
from app.models import User
from app.services.auth.authentication import AuthenticationError, user_from_access_token


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int | None
    username: str
    display_name: str | None
    is_legacy_system: bool = False


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> Principal:
    if credentials is None:
        if get_settings().auth_mode == "optional":
            return Principal(None, "legacy-system", "Legacy development mode", True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        user = user_from_access_token(db, credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"}) from exc
    return Principal(user.id, user.username, user.display_name)


def require_authenticated_user(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
    if principal.user_id is None and not principal.is_legacy_system:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def require_real_user(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
    if principal.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
RealPrincipal = Annotated[Principal, Depends(require_real_user)]
