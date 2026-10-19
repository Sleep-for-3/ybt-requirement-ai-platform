"""Project-scope binding gaps, surfaced before an agent run instead of inside it.

The runtime resolves a Skill only through an explicit ``AISkillScopeBinding``: a
published version alone is never adopted automatically.  That is the right
safety rule, but it used to surface only as a ``skill_binding_missing`` gap in
the middle of an agent task.  This module answers the configuration question up
front: for one scope, which Skills have no binding yet, and which published
version would the operator pin if they act on the todo.

Nothing here writes: acting on a todo still goes through ``releases.adopt``.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AISkillDefinition, AISkillScopeBinding, AISkillVersion
from app.schemas.ai_skill import SkillScope
from app.services.ai_skills import evaluation
from app.services.ai_skills.control import scope_key


def _published_for(db: Session, definition_id: int, scope: SkillScope) -> list[AISkillVersion]:
    versions = db.scalars(select(AISkillVersion).where(
        AISkillVersion.definition_id == definition_id,
        AISkillVersion.status == "published",
        AISkillVersion.published_at.is_not(None),
    ).order_by(AISkillVersion.version_no.desc())).all()
    return [item for item in versions if evaluation.compatible_owner(item, scope)]


def _availability(db: Session, version: AISkillVersion) -> bool:
    try:
        return version.release_dependency_hash == evaluation.dependencies(db, version)
    except HTTPException:
        # A published record whose dependencies cannot even be evaluated is not
        # installable; report it as unavailable instead of failing the whole list.
        return False


def _todo(definition: AISkillDefinition, latest: AISkillVersion | None, scope: SkillScope) -> dict[str, Any]:
    key = definition.skill_key
    return {
        "code": "bind_skill_version",
        "label": f"固定采用「{definition.display_name}」的已发布版本",
        "skill_key": key,
        "task_key": definition.task_key,
        "display_name": definition.display_name,
        "scope": scope.model_dump(),
        "latest_published": None if latest is None else {
            "id": latest.id,
            "version_no": latest.version_no,
            "scope_type": latest.scope_type,
            "content_hash": latest.content_hash,
        },
        "api": f"/ai-skills/{key}/binding-options",
        "bind_api": f"/ai-skills/{key}/bindings",
    }


def binding_todos(db: Session, scope: SkillScope) -> list[dict[str, Any]]:
    """Every Skill that has no binding at ``scope``, with its newest published version.

    Only project/task scopes carry a binding, so other scopes yield an empty list
    rather than an error: the configuration centre renders the same call for every
    scope it offers.
    """
    if scope.scope_type not in {"project", "task"}:
        return []
    key = scope_key(scope)
    bound = {row for row in db.scalars(
        select(AISkillScopeBinding.definition_id).where(AISkillScopeBinding.scope_key == key)).all()}
    todos: list[dict[str, Any]] = []
    for definition in db.scalars(select(AISkillDefinition).order_by(AISkillDefinition.skill_key)).all():
        if definition.id in bound:
            continue
        published = _published_for(db, definition.id, scope)
        latest = published[0] if published else None
        item = _todo(definition, latest, scope)
        item["available"] = latest is not None and _availability(db, latest)
        item["reason"] = "no_binding" if latest is not None else "no_published_version"
        todos.append(item)
    return todos
