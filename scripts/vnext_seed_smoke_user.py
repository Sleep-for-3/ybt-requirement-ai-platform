"""为真实组件冒烟准备登录用户与项目成员关系（写入真实 PostgreSQL）。

仅用于本地隔离冒烟库 ybt_dsh_handoff_v2，不触碰任何生产库。
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import Project, User  # noqa: E402
from app.models.governance import ProjectMembership  # noqa: E402
from app.services.auth.password import hash_password  # noqa: E402

USERNAME = "vnext-smoke"
PASSWORD = "VnextSmoke#2026"


def main() -> int:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == USERNAME))
        if user is None:
            user = User(username=USERNAME, display_name="VNext 冒烟账号", password_hash=hash_password(PASSWORD), status="active")
            db.add(user)
            db.flush()
        project = db.get(Project, 1)
        if project is None:
            print("project 1 missing")
            return 1
        if project.project_owner_id is None:
            project.project_owner_id = user.id
        membership = db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id
            )
        )
        if membership is None:
            membership = ProjectMembership(project_id=project.id, user_id=user.id, project_role="project_manager", status="active")
            db.add(membership)
        else:
            membership.project_role = "project_manager"
            membership.status = "active"
        db.commit()
        print(f"user_id={user.id} username={user.username} project={project.id} owner={project.project_owner_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
