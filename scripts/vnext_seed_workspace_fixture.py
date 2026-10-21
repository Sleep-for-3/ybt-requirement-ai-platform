"""为真实页面点检准备最小工作区数据（写入真实 PostgreSQL 隔离库）。

- 复用已有 project 1（不存在则创建）与 vnext-smoke 账号；
- 建一表通目标表与两个目标字段（客户统一标识 / 产品编号）；
- 建一条合成监管需求，scope 指向该目标表与两个字段。

可重复执行：同名对象复用，不删除任何既有数据。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import Project, TargetField, TargetTable, User  # noqa: E402
from app.models.governance import Institution, ProjectMembership  # noqa: E402
from app.models.requirement import Requirement  # noqa: E402

PROJECT_ID = 1
TABLE_CODE = "EAST_YBT_CUSTOMER"
TABLE_NAME = "一表通客户信息表"
FIELDS = [
    ("CUSTOMER_ID", "客户统一标识", "varchar(64)", "客户在银行内部的统一编号，按客户粒度报送。"),
    ("PRODUCT_ID", "产品编号", "varchar(32)", "客户持有产品的内部产品编号；同一客户多个产品需按产品粒度报送。"),
]
REQUIREMENT_NAME = "根据借据信息取得产品信息（VNext 真实页面点检）"
BACKGROUND = "根据借据信息中的产品编号与期限，取产品信息并形成一表通客户产品口径。"


def main() -> int:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "vnext-smoke"))
        if user is None:
            print("missing vnext-smoke; run scripts/vnext_seed_smoke_user.py first")
            return 1
        project = db.get(Project, PROJECT_ID)
        if project is None:
            institution = db.scalar(select(Institution).where(Institution.institution_code == "VNEXT-SYNTH"))
            if institution is None:
                institution = Institution(institution_code="VNEXT-SYNTH", institution_name="VNext 合成验证机构")
                db.add(institution)
                db.flush()
            project = Project(name="VNext 真实页面点检项目", institution_id=institution.id,
                              project_owner_id=user.id, description="合成数据，非真实银行业务")
            db.add(project)
            db.flush()
        elif project.project_owner_id is None:
            project.project_owner_id = user.id
        if project.institution_id is None:
            institution = db.scalar(select(Institution).where(Institution.institution_code == "VNEXT-SYNTH"))
            if institution is None:
                institution = Institution(institution_code="VNEXT-SYNTH", institution_name="VNext 合成验证机构")
                db.add(institution)
                db.flush()
            project.institution_id = institution.id
        membership = db.scalar(select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id))
        if membership is None:
            db.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
        else:
            membership.project_role = "project_manager"
            membership.status = "active"

        table = db.scalar(select(TargetTable).where(
            TargetTable.project_id == project.id, TargetTable.table_code == TABLE_CODE))
        if table is None:
            table = TargetTable(project_id=project.id, table_code=TABLE_CODE, table_name=TABLE_NAME,
                                description="合成一表通客户表（页面点检用）")
            db.add(table)
            db.flush()
        field_ids: list[int] = []
        for code, name, ftype, definition in FIELDS:
            field = db.scalar(select(TargetField).where(
                TargetField.project_id == project.id, TargetField.target_table_id == table.id,
                TargetField.field_code == code))
            if field is None:
                field = TargetField(project_id=project.id, target_table_id=table.id,
                                    field_code=code, field_name=name, field_type=ftype,
                                    required_flag=True, field_definition=definition)
                db.add(field)
                db.flush()
            field_ids.append(int(field.id))

        requirement = db.scalar(select(Requirement).where(
            Requirement.project_id == project.id, Requirement.name == REQUIREMENT_NAME))
        scope = {
            "target_table_id": int(table.id),
            "field_ids": field_ids,
            "scenario_id": None,
            "background": BACKGROUND,
        }
        if requirement is None:
            requirement = Requirement(project_id=project.id, name=REQUIREMENT_NAME, version=1,
                                      scope_json=scope, content_version=0)
            db.add(requirement)
            db.flush()
        else:
            requirement.scope_json = {**(requirement.scope_json or {}), **scope}
        db.commit()
        print(json.dumps({
            "project_id": project.id,
            "user_id": user.id,
            "target_table_id": table.id,
            "target_field_ids": field_ids,
            "requirement_id": requirement.id,
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
