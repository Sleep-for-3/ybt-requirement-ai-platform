from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Institution, InstitutionMembership, User
from app.schemas.governance import AdminUserCreate, BootstrapRequest, BootstrapResponse, InstitutionCreate, InstitutionRead, UserRead
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import INSTITUTION_ROLES, PROJECT_ROLE_PERMISSIONS, PermissionService
from app.services.auth.password import hash_password


router = APIRouter(prefix="/admin", tags=["administration"])


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=status.HTTP_201_CREATED)
def bootstrap(payload: BootstrapRequest, db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(func.count(User.id))) > 0 or db.scalar(select(func.count(Institution.id))) > 0:
        raise HTTPException(status_code=409, detail="Platform has already been bootstrapped")
    institution = Institution(
        institution_code=payload.institution_code.strip().upper(),
        institution_name=payload.institution_name.strip(),
        institution_type=payload.institution_type,
        status="active",
    )
    user = User(
        username=payload.username.strip().lower(),
        display_name=payload.display_name.strip(),
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        status="active",
    )
    db.add_all([institution, user])
    db.flush()
    db.add(InstitutionMembership(
        institution_id=institution.id,
        user_id=user.id,
        role="institution_admin",
        status="active",
        created_by=user.id,
    ))
    db.commit()
    db.refresh(user)
    return {"institution_id": institution.id, "user": user}


@router.get("/institutions", response_model=list[InstitutionRead])
def list_institutions(principal: RealPrincipal, db: Session = Depends(get_db)) -> list[Institution]:
    permissions = PermissionService(db, principal)
    if permissions.is_platform_admin():
        return list(db.scalars(select(Institution).order_by(Institution.institution_name)).all())
    ids = select(InstitutionMembership.institution_id).where(
        InstitutionMembership.user_id == principal.user_id,
        InstitutionMembership.status == "active",
    )
    return list(db.scalars(select(Institution).where(Institution.id.in_(ids)).order_by(Institution.institution_name)).all())


@router.post("/institutions", response_model=InstitutionRead, status_code=201)
def create_institution(payload: InstitutionCreate, principal: RealPrincipal, db: Session = Depends(get_db)) -> Institution:
    if not PermissionService(db, principal).is_platform_admin():
        raise HTTPException(status_code=403, detail="Platform administrator required")
    if payload.institution_type not in {"bank", "consulting_company", "platform_operator"}:
        raise HTTPException(status_code=400, detail="Invalid institution type")
    institution = Institution(
        institution_code=payload.institution_code.strip().upper(),
        institution_name=payload.institution_name.strip(),
        institution_type=payload.institution_type,
        status="active",
        data_classification_policy_json=payload.data_classification_policy_json,
    )
    db.add(institution)
    db.commit()
    db.refresh(institution)
    return institution


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(payload: AdminUserCreate, principal: RealPrincipal, db: Session = Depends(get_db)) -> User:
    PermissionService(db, principal).require_institution_role(payload.institution_id, {"institution_admin", "security_admin"})
    if payload.institution_role not in INSTITUTION_ROLES:
        raise HTTPException(status_code=400, detail="Invalid institution role")
    user = User(
        username=payload.username.strip().lower(),
        display_name=payload.display_name.strip(),
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        status="active",
    )
    db.add(user)
    db.flush()
    db.add(InstitutionMembership(
        institution_id=payload.institution_id,
        user_id=user.id,
        role=payload.institution_role,
        status="active",
        created_by=principal.user_id,
    ))
    db.commit()
    db.refresh(user)
    return user


@router.get("/permissions")
def permissions(principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    if not PermissionService(db, principal).is_platform_admin():
        raise HTTPException(status_code=403, detail="Platform administrator required")
    return {"institution_roles": sorted(INSTITUTION_ROLES), "project_roles": {role: sorted(values) for role, values in PROJECT_ROLE_PERMISSIONS.items()}}
