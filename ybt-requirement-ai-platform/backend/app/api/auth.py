from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import InstitutionMembership, ProjectMembership, User
from app.schemas.governance import AuthMe, LoginRequest, RefreshRequest, TokenResponse
from app.services.auth.authentication import AuthenticationError, authenticate, create_session, revoke_refresh_token, rotate_refresh_token
from app.services.auth.dependencies import RealPrincipal
from app.services.governance.audit import record_audit


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        user = authenticate(db, payload.username, payload.password)
    except AuthenticationError as exc:
        record_audit(db, action="login", resource_type="user_session", result="failed", request_id=getattr(request.state, "request_id", None), ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password") from exc
    session = create_session(db, user)
    institution_id = db.scalar(select(InstitutionMembership.institution_id).where(InstitutionMembership.user_id == user.id, InstitutionMembership.status == "active").limit(1))
    record_audit(db, action="login", resource_type="user_session", resource_id=user.id, actor_user_id=user.id, institution_id=institution_id, request_id=getattr(request.state, "request_id", None), ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    db.commit()
    return session


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return rotate_refresh_token(db, payload.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc


@router.post("/logout")
def logout(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    user_id = revoke_refresh_token(db, payload.refresh_token)
    record_audit(db, action="logout", resource_type="user_session", resource_id=user_id, actor_user_id=user_id, request_id=getattr(request.state, "request_id", None), ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    db.commit()
    return {"status": "logged_out"}


@router.get("/me", response_model=AuthMe)
def me(principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, principal.user_id)
    institution_memberships = list(db.execute(select(
        InstitutionMembership.institution_id,
        InstitutionMembership.role,
        InstitutionMembership.status,
    ).where(InstitutionMembership.user_id == user.id)).mappings())
    project_memberships = list(db.execute(select(
        ProjectMembership.project_id,
        ProjectMembership.project_role,
        ProjectMembership.status,
    ).where(ProjectMembership.user_id == user.id)).mappings())
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "status": user.status,
        "last_login_at": user.last_login_at,
        "institution_memberships": [dict(item) for item in institution_memberships],
        "project_memberships": [dict(item) for item in project_memberships],
    }
