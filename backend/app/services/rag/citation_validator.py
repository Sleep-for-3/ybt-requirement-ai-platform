from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeUnit


def validate_citations(
    db: Session,
    citations: list[dict],
    *,
    project_id: int | None = None,
    institution_name: str | None = None,
) -> None:
    """Reject citations that do not resolve to visible, enabled knowledge units."""
    ids = {
        citation.get("knowledge_unit_id")
        for citation in citations
        if citation.get("knowledge_unit_id") is not None
    }
    if len(ids) != len(citations):
        raise ValueError("citation 缺少 knowledge_unit_id")
    if not ids:
        return

    units = {
        unit.id: unit
        for unit in db.scalars(
            select(KnowledgeUnit).where(
                KnowledgeUnit.id.in_(ids),
                KnowledgeUnit.enabled.is_(True),
            )
        ).all()
    }
    missing = ids - units.keys()
    if missing:
        raise ValueError(f"citation 对应的 KnowledgeUnit 不存在或已禁用: {sorted(missing)}")
    if project_id is None:
        return
    invisible = [
        unit.id
        for unit in units.values()
        if not (
            (unit.knowledge_scope == "global" and (unit.project_id == project_id or unit.confidentiality_level != "restricted"))
            or (unit.knowledge_scope in {"project", "institution"} and unit.project_id == project_id)
        )
    ]
    if invisible:
        raise ValueError(f"citation 对当前项目不可见: {sorted(invisible)}")
