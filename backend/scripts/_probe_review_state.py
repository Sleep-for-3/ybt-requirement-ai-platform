"""一次性只读勘察：T_5_1 的版本作者、项目成员、历史送审与工作流步骤。"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ProjectMembership,
    RequirementRevision,
    RequirementReviewSubmission,
    ReviewTask,
    User,
    WorkflowDefinition,
    WorkflowInstance,
)


def main() -> None:
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).order_by(User.id)))
        print("users:", [(u.id, u.username, u.display_name if hasattr(u, "display_name") else "") for u in users])
        members = list(
            db.scalars(select(ProjectMembership).where(ProjectMembership.project_id == 9))
        )
        print("project members:", [(m.user_id, getattr(m, "role", None)) for m in members])
        revisions = list(
            db.scalars(
                select(RequirementRevision)
                .where(RequirementRevision.requirement_id == 30)
                .order_by(RequirementRevision.content_version)
            )
        )
        print(
            "revisions:",
            [
                (r.content_version, r.status, r.created_by, (r.content_hash or "")[:12])
                for r in revisions
            ],
        )
        submissions = list(
            db.scalars(
                select(RequirementReviewSubmission).where(
                    RequirementReviewSubmission.requirement_id == 30
                )
            )
        )
        print(
            "submissions:",
            [(s.id, s.status, s.content_version, s.submitted_by) for s in submissions],
        )
        definitions = list(
            db.scalars(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.workflow_key == "requirement_document_review"
                )
            )
        )
        for definition in definitions:
            print("workflow definition:", definition.workflow_key, definition.steps_json)
        instances = list(
            db.scalars(
                select(WorkflowInstance)
                .where(WorkflowInstance.project_id == 9)
                .order_by(WorkflowInstance.id.desc())
                .limit(5)
            )
        )
        print(
            "recent workflows:",
            [(w.id, w.workflow_key, w.status, w.current_step) for w in instances],
        )
        tasks = list(
            db.scalars(
                select(ReviewTask).where(ReviewTask.project_id == 9).order_by(ReviewTask.id.desc()).limit(10)
            )
        )
        print(
            "recent tasks:",
            [(t.id, t.step_key, t.status, t.assignee_user_id, t.target_type, t.target_id) for t in tasks],
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
