"""Control-plane operations share the caller's transaction and never commit."""
from string import Formatter

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import AISkillDefinition, AISkillVersion, AISkillReleaseEvent, Institution, ModelProfile, User
from app.schemas.ai_skill import SkillScope
from app.schemas.ai_skill_control import SkillContent, SkillDefinitionCreate, SkillVersionCreate, SkillVersionEdit
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.llm.execution_metadata import stable_hash

VARIABLES = frozenset({"subject", "facts", "policy_evidence", "gaps"})


def fail(status: int, code: str):
    raise HTTPException(status, detail={"error_code": code})


def scope_key(scope: SkillScope) -> str:
    if scope.scope_type == "platform":
        return "platform"
    if scope.scope_type == "institution":
        return f"institution:{scope.institution_id}"
    base = f"project:{scope.institution_id}:{scope.project_id}"
    return base if scope.scope_type == "project" else f"{base}:task:{scope.invocation_key}"


def version_scope(version: AISkillVersion) -> SkillScope:
    return SkillScope(scope_type=version.scope_type, institution_id=version.institution_id,
                      project_id=version.project_id, invocation_key=version.invocation_key)


def require_user(db, principal):
    user = db.get(User, principal.user_id) if principal.user_id is not None and not principal.is_legacy_system else None
    if user is None or user.status != "active":
        fail(401, "authentication_required")


def authorize_scope(db, principal, scope: SkillScope, *, write=False, publish=False):
    require_user(db, principal)
    permissions = PermissionService(db, principal)
    if scope.scope_type == "platform":
        if not permissions.is_platform_admin():
            fail(403, "insufficient_permission")
        return
    if scope.project_id is not None:
        project = permissions.require_project_permission(scope.project_id, "knowledge.manage")
        if project.institution_id != scope.institution_id:
            fail(404, "resource_not_found")
        if write and project.project_status != "active":
            fail(409, "project_inactive")
    else:
        permissions.require_institution_role(scope.institution_id, {"institution_admin", "security_admin"})
    institution = db.get(Institution, scope.institution_id)
    if institution is None or institution.status != "active":
        fail(404, "resource_not_found")
    if publish:
        permissions.require_institution_role(scope.institution_id, {"institution_admin", "security_admin"})


def definition_for(db, key: str) -> AISkillDefinition:
    item = db.scalar(select(AISkillDefinition).where(AISkillDefinition.skill_key == key))
    if item is None:
        fail(404, "resource_not_found")
    return item


def version_for(db, principal, key, version_no, *, write=False, publish=False):
    require_user(db, principal)
    definition = definition_for(db, key)
    version = db.scalar(select(AISkillVersion).where(AISkillVersion.definition_id == definition.id,
                                                  AISkillVersion.version_no == version_no))
    if version is None:
        fail(404, "resource_not_found")
    authorize_scope(db, principal, version_scope(version), write=write, publish=publish)
    return version


def validate_content(db, content: SkillContent):
    model = db.get(ModelProfile, content.model_profile_id)
    if model is None or not model.enabled:
        fail(422, "model_profile_unavailable")
    try:
        referenced = set()
        for _, field, spec, conversion in Formatter().parse(content.user_prompt_template):
            if field is not None and (field not in VARIABLES or spec or conversion):
                fail(422, "invalid_template_variable")
            if field is not None:
                referenced.add(field)
        if referenced != VARIABLES:
            fail(422, "missing_template_evidence")
    except ValueError:
        fail(422, "invalid_template")


def event(db, principal, definition_id, version, action, detail=None, *, scope=None):
    scope = scope or (version_scope(version) if version else SkillScope(scope_type="platform"))
    db.add(AISkillReleaseEvent(definition_id=definition_id, version_id=version.id if version else None,
                             scope_key=scope_key(scope), action=action, actor_user_id=principal.user_id,
                             detail_json=detail or {}))
    record_audit(db, action=f"ai_skill_{action}", resource_type="ai_skill_version" if version else "ai_skill",
                 resource_id=version.id if version else definition_id, actor_user_id=principal.user_id,
                 institution_id=scope.institution_id, project_id=scope.project_id, after=detail or {})


def create_definition(db, principal, payload: SkillDefinitionCreate):
    authorize_scope(db, principal, SkillScope(scope_type="platform"), write=True)
    try:
        with db.begin_nested():
            item = AISkillDefinition(**payload.model_dump(), created_by=principal.user_id)
            db.add(item)
            db.flush()
    except IntegrityError:
        fail(409, "skill_key_exists")
    event(db, principal, item.id, None, "created")
    return item


def create_version(db, principal, key, payload: SkillVersionCreate, *, restored_from=None):
    authorize_scope(db, principal, payload.scope, write=True)
    definition = definition_for(db, key)
    validate_content(db, payload.content)
    # An atomic counter serializes concurrent allocations on both supported DBs.
    allocated = db.scalar(update(AISkillDefinition).where(AISkillDefinition.id == definition.id)
                          .values(next_version_no=AISkillDefinition.next_version_no + 1)
                          .returning(AISkillDefinition.next_version_no)) - 1
    content = payload.content.model_dump(mode="json")
    item = AISkillVersion(definition_id=definition.id, version_no=allocated,
                          **payload.scope.model_dump(), scope_key=scope_key(payload.scope),
                          content_json=content, content_hash=stable_hash(content),
                          created_by=principal.user_id, edited_by=principal.user_id,
                          restored_from_version_id=restored_from)
    db.add(item)
    db.flush()
    event(db, principal, definition.id, item, "restored" if restored_from else "draft_created",
          {"content_hash": item.content_hash, "restored_from_version_id": restored_from})
    return item


def edit_version(db, principal, key, number, payload: SkillVersionEdit):
    item = version_for(db, principal, key, number, write=True)
    validate_content(db, payload.content)
    content = payload.content.model_dump(mode="json")
    changed = db.execute(update(AISkillVersion).where(
        AISkillVersion.id == item.id, AISkillVersion.status == "draft", AISkillVersion.published_at.is_(None),
        AISkillVersion.lock_version == payload.expected_lock_version,
    ).values(content_json=content, content_hash=stable_hash(content), edited_by=principal.user_id,
             lock_version=AISkillVersion.lock_version + 1, test_epoch=AISkillVersion.test_epoch + 1))
    if changed.rowcount != 1:
        fail(409, "version_conflict")
    db.refresh(item)
    event(db, principal, item.definition_id, item, "draft_edited", {"content_hash": item.content_hash})
    return item


def restore_version(db, principal, key, number):
    source = version_for(db, principal, key, number, write=True)
    if source.status not in {"published", "deprecated", "archived"}:
        fail(409, "restore_requires_published_history")
    return create_version(db, principal, key, SkillVersionCreate(scope=version_scope(source),
                          content=SkillContent.model_validate(source.content_json)), restored_from=source.id)


