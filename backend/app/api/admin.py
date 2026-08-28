from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Institution, InstitutionMembership, User
from app.schemas.governance import AdminUserCreate, AdminUserRead, BootstrapRequest, BootstrapResponse, InstitutionCreate, InstitutionRead, UserRead
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
    if not permissions.capabilities()["can_view_admin"]:
        raise HTTPException(status_code=403, detail="Administrator capability required")
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


@router.get("/users", response_model=list[AdminUserRead])
def list_users(principal: RealPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    permissions = PermissionService(db, principal)
    visible_institution_ids: list[int] | None = None
    if not permissions.is_platform_admin():
        visible_institution_ids = list(db.scalars(select(InstitutionMembership.institution_id).where(
            InstitutionMembership.user_id == principal.user_id,
            InstitutionMembership.status == "active",
            InstitutionMembership.role.in_(("institution_admin", "security_admin")),
        )).all())
        if not visible_institution_ids:
            raise HTTPException(status_code=403, detail="Institution administrator required")

    statement = select(User, InstitutionMembership, Institution).join(
        InstitutionMembership, InstitutionMembership.user_id == User.id,
    ).join(
        Institution, Institution.id == InstitutionMembership.institution_id,
    ).where(
        InstitutionMembership.status == "active",
        Institution.status == "active",
    ).order_by(User.display_name, User.username, Institution.institution_name)
    if visible_institution_ids is not None:
        statement = statement.where(InstitutionMembership.institution_id.in_(visible_institution_ids))

    directory: dict[int, dict] = {}
    for user, membership, institution in db.execute(statement).all():
        item = directory.setdefault(user.id, {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "status": user.status,
            "last_login_at": user.last_login_at,
            "institution_memberships": [],
        })
        item["institution_memberships"].append({
            "institution_id": institution.id,
            "institution_name": institution.institution_name,
            "role": membership.role,
            "status": membership.status,
        })
    return list(directory.values())


@router.get("/permissions")
def permissions(principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    if not PermissionService(db, principal).capabilities()["can_view_permission_matrix"]:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    return {"institution_roles": sorted(INSTITUTION_ROLES), "project_roles": {role: sorted(values) for role, values in PROJECT_ROLE_PERMISSIONS.items()}}
