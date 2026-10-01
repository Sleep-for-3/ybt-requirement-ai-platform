"""Atomic release, explicit pinned adoption, and immutable-history restoration."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import AISkillDefinition, AISkillVersion, AISkillScopeBinding, ModelProfile, PromptTemplateVersion
from app.services.ai_skills import control, evaluation, runtime


def _set_binding(db, principal, version, scope, expected_lock):
    control.authorize_scope(db, principal, scope, write=True, publish=True)
    if not evaluation.compatible_owner(version, scope):
        control.fail(404, "resource_not_found")
    if version.status != "published" or version.published_at is None:
        control.fail(409, "binding_requires_published_version")
    if version.release_dependency_hash != evaluation.dependencies(db, version):
        control.fail(409, "skill_dependency_changed")
    key = control.scope_key(scope)
    current = db.scalar(select(AISkillScopeBinding).where(AISkillScopeBinding.definition_id == version.definition_id,
                                                       AISkillScopeBinding.scope_key == key))
    inherited = version.scope_key if version.scope_key != key else None
    if current is None:
        if expected_lock is not None:
            control.fail(409, "binding_conflict")
        try:
            with db.begin_nested():
                current = AISkillScopeBinding(definition_id=version.definition_id, version_id=version.id,
                    **scope.model_dump(), scope_key=key, inherited_from_scope=inherited, updated_by=principal.user_id)
                db.add(current)
                db.flush()
        except IntegrityError:
            control.fail(409, "binding_conflict")
    else:
        changed = db.execute(update(AISkillScopeBinding).where(AISkillScopeBinding.id == current.id,
                     AISkillScopeBinding.lock_version == expected_lock).values(version_id=version.id,
                     inherited_from_scope=inherited, updated_by=principal.user_id, lock_version=AISkillScopeBinding.lock_version + 1))
        if changed.rowcount != 1:
            control.fail(409, "binding_conflict")
        db.refresh(current)
    control.event(db, principal, version.definition_id, version, "bound", {"binding_id": current.id, "target_scope": key,
                                                                         "binding_lock": current.lock_version})
    return current


def adopt(db, principal, key, payload):
    control.authorize_scope(db, principal, payload.scope, write=True, publish=True)
    definition = control.definition_for(db, key)
    version = db.scalar(select(AISkillVersion).where(AISkillVersion.definition_id == definition.id,
                                                  AISkillVersion.version_no == payload.version))
    if version is None or not evaluation.compatible_owner(version, payload.scope):
        control.fail(404, "resource_not_found")
    return _set_binding(db, principal, version, payload.scope, payload.expected_binding_lock)


def reset_draft(db, principal, key, number, expected_lock):
    version = control.version_for(db, principal, key, number, write=True)
    changed = db.execute(update(AISkillVersion).where(AISkillVersion.id == version.id,
        AISkillVersion.status.in_(["testing", "pending_approval"]), AISkillVersion.published_at.is_(None),
        AISkillVersion.lock_version == expected_lock).values(status="draft", approved_by=None,
        lock_version=AISkillVersion.lock_version + 1, test_epoch=AISkillVersion.test_epoch + 1))
    if changed.rowcount != 1:
        control.fail(409, "version_conflict")
    db.refresh(version)
    control.event(db, principal, version.definition_id, version, "returned_to_draft")
    return version


def submit(db, principal, key, number, payload):
    version = control.version_for(db, principal, key, number, write=True)
    evaluation.test_scope(db, principal, payload.test_project_id)
    runs = evaluation.release_evidence(db, version, payload.test_project_id)
    changed = db.execute(update(AISkillVersion).where(AISkillVersion.id == version.id, AISkillVersion.status == "testing",
              AISkillVersion.lock_version == payload.expected_lock_version).values(status="pending_approval", lock_version=AISkillVersion.lock_version + 1))
    if changed.rowcount != 1:
        control.fail(409, "version_conflict")
    db.refresh(version)
    control.event(db, principal, version.definition_id, version, "submitted", {"test_run_ids": runs})
    return version


def publish(db, principal, key, number, payload):
    version = control.version_for(db, principal, key, number, write=True, publish=True)
    evaluation.test_scope(db, principal, payload.test_project_id)
    if principal.user_id in {version.created_by, version.edited_by}:
        control.fail(403, "independent_approval_required")
    # Lock the definition before checking mutable profile/tests and writing a
    # snapshot. All release writes still roll back together on any failure.
    db.execute(update(AISkillDefinition).where(AISkillDefinition.id == version.definition_id)
               .values(next_version_no=AISkillDefinition.next_version_no))
    db.scalar(select(ModelProfile).where(ModelProfile.id == version.content_json["model_profile_id"]).with_for_update().execution_options(populate_existing=True))
    runs = evaluation.release_evidence(db, version, payload.test_project_id)
    changed = db.execute(update(AISkillVersion).where(AISkillVersion.id == version.id,
        AISkillVersion.status == "pending_approval", AISkillVersion.published_at.is_(None),
        AISkillVersion.lock_version == payload.expected_lock_version).values(status="published",
        published_at=datetime.now(timezone.utc), approved_by=principal.user_id,
        release_dependency_hash=evaluation.dependencies(db, version), lock_version=AISkillVersion.lock_version + 1))
    if changed.rowcount != 1:
        control.fail(409, "version_conflict")
    db.refresh(version)
    definition = db.get(AISkillDefinition, version.definition_id)
    db.add(PromptTemplateVersion(prompt_key=f"ai_skill:{definition.skill_key}", version_no=version.version_no,
        system_prompt=version.content_json["system_prompt"], user_prompt_template=version.content_json["user_prompt_template"],
        output_schema_json=runtime.output_schema(definition.task_key).model_json_schema(), enabled=True, skill_version_id=version.id,
        created_by=principal.username, change_note="Immutable Skill compatibility snapshot"))
    binding = _set_binding(db, principal, version, control.version_scope(version), payload.expected_binding_lock)
    control.event(db, principal, definition.id, version, "published", {"test_run_ids": runs, "content_hash": version.content_hash,
                                                                     "binding_id": binding.id})
    db.flush()
    return version


def deprecate(db, principal, key, number, expected_lock):
    version = control.version_for(db, principal, key, number, write=True, publish=True)
    changed = db.execute(update(AISkillVersion).where(AISkillVersion.id == version.id,
        AISkillVersion.status == "published", AISkillVersion.lock_version == expected_lock)
        .values(status="deprecated", lock_version=AISkillVersion.lock_version + 1))
    if changed.rowcount != 1:
        control.fail(409, "version_conflict")
    db.refresh(version)
    control.event(db, principal, version.definition_id, version, "deprecated")
    return version
