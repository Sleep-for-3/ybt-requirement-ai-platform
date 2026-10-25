"""Provision a platform-operator institution + admin for the 2026-10-24 delivery run.

The dev database was bootstrapped earlier by another project (VNEXT-SYNTH), so
`POST /api/admin/bootstrap` refuses to run again. This script inserts the same
records the bootstrap endpoint would create, using the application's own
PasswordHasher so the resulting account logs in through the normal API.

Idempotent: re-running only re-activates the membership / resets the password.

    cd ai-platform/backend
    ./.venv/Scripts/python.exe ../scripts/e2e_provision.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Institution, InstitutionMembership, User  # noqa: E402
from app.services.auth.password import hash_password  # noqa: E402

INSTITUTION_CODE = "YBT-PLATFORM"
INSTITUTION_NAME = "一表通交付平台运营方"
INSTITUTION_TYPE = "platform_operator"
USERNAME = "ybt-lead"
DISPLAY_NAME = "一表通交付负责人"
EMAIL = "ybt-lead@example.com"
PASSWORD = "Ybt#20261024lead"


def main() -> int:
    with SessionLocal() as db:
        institution = db.scalar(select(Institution).where(Institution.institution_code == INSTITUTION_CODE))
        if institution is None:
            institution = Institution(
                institution_code=INSTITUTION_CODE,
                institution_name=INSTITUTION_NAME,
                institution_type=INSTITUTION_TYPE,
                status="active",
                data_classification_policy_json={},
            )
            db.add(institution)
            db.flush()
            print(f"created institution {institution.id} {INSTITUTION_CODE}")
        else:
            institution.institution_type = INSTITUTION_TYPE
            institution.status = "active"
            print(f"reused institution {institution.id} {INSTITUTION_CODE}")

        user = db.scalar(select(User).where(User.username == USERNAME))
        if user is None:
            user = User(
                username=USERNAME,
                display_name=DISPLAY_NAME,
                email=EMAIL,
                password_hash=hash_password(PASSWORD),
                status="active",
            )
            db.add(user)
            db.flush()
            print(f"created user {user.id} {USERNAME}")
        else:
            user.password_hash = hash_password(PASSWORD)
            user.status = "active"
            print(f"reused user {user.id} {USERNAME} (password reset)")

        membership = db.scalar(select(InstitutionMembership).where(
            InstitutionMembership.user_id == user.id,
            InstitutionMembership.institution_id == institution.id,
        ))
        if membership is None:
            membership = InstitutionMembership(
                institution_id=institution.id,
                user_id=user.id,
                role="institution_admin",
                status="active",
            )
            db.add(membership)
            print("created institution_admin membership")
        else:
            membership.role = "institution_admin"
            membership.status = "active"
            print("updated membership to institution_admin")

        db.commit()
        print(f"\nlogin: username={USERNAME} password={PASSWORD}")
        print(f"institution_id={institution.id} user_id={user.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
