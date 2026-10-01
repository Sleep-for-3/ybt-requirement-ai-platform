"""Executable B5 cache boundary, not a cache store or an enabled runtime cache.

Only server-built lineage evidence is accepted. A hit is a revalidated historical
candidate, never a new model run. Call with a request-scoped database transaction.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import InstitutionMembership, ModelCallLog, ProjectMembership
from app.schemas.ai_skill import SkillInputEnvelope, SkillScope, validate_claim_references, validate_policy_comparison
from app.services.ai_skills import runtime
from app.services.ai_skills.control import fail
from app.services.ai_skills.lineage_adapter import build_envelope
from app.services.auth.permission_service import PermissionService
from app.services.lineage.explanation import build_lineage_edge_context
from app.services.llm.execution_metadata import stable_hash

CACHE_CONTRACT_VERSION = "skill-cache-1"
MAX_TTL_SECONDS = 300


@dataclass(frozen=True)
class CacheAccess:
    key: str
    envelope: SkillInputEnvelope
    skill_version_id: int
    binding_id: int
    model_profile_id: int
    provider: str
    expected_model: str | None


@dataclass(frozen=True)
class CacheCandidate:
    key: str
    result: dict
    origin_run_id: int
    expires_at: datetime


def prepare_lineage_access(db, principal, project_id, request):
    # Refresh identities even when the caller previously loaded them in this
    # request. Do not commit or replace the caller's transaction.
    db.flush()
    db.expire_all()
    project = PermissionService(db, principal).require_project_permission(project_id, "project.view")
    if project.institution_id is None:
        return None
    scope = SkillScope(scope_type="task", institution_id=project.institution_id,
                       project_id=project_id, invocation_key="lineage_graph")
    resolved = runtime.resolve_skill(db, principal, "lineage_edge_explanation", scope)
    if resolved is None:
        return None
    definition, version, binding = resolved
    context = build_lineage_edge_context(db, project_id, str(request.edge_id), request.revision_id)
    envelope, _ = build_envelope(db, project, request, context, definition, version)
    compiled = runtime.compile_input(db, definition, version, envelope)
    memberships = list(db.execute(select(ProjectMembership.project_role, ProjectMembership.status).where(
        ProjectMembership.project_id == project_id, ProjectMembership.user_id == principal.user_id)))
    institution_roles = list(db.execute(select(InstitutionMembership.institution_id, InstitutionMembership.role,
        InstitutionMembership.status).where(InstitutionMembership.user_id == principal.user_id)
        .order_by(InstitutionMembership.institution_id)))
    expected_model = "mock-llm" if compiled.runtime.provider_type == "mock" else compiled.runtime.model_name
    key = stable_hash({"contract": CACHE_CONTRACT_VERSION, "actor": principal.user_id,
        "permissions": [list(row) for row in memberships], "institution_roles": [list(row) for row in institution_roles],
        "scope": scope.model_dump(), "binding_id": binding.id, "version_id": version.id,
        "content_hash": version.content_hash, "dependency_hash": version.release_dependency_hash,
        "context_hash": envelope.context_hash(), "confidentiality": compiled.confidentiality,
        "request_hash": stable_hash([compiled.runtime.system_prompt, compiled.input_text]),
        "model_profile_id": compiled.runtime.model_profile_id, "provider": compiled.runtime.provider_type,
        "actual_model": expected_model})
    return CacheAccess(key, envelope, version.id, binding.id, compiled.runtime.model_profile_id,
                       compiled.runtime.provider_type, expected_model)


def _validated_payload(db, access, result, run_id):
    """Tie the candidate to the successful stored run, then recheck its schema."""
    metadata = result.get("execution_metadata", {})
    payload = {key: value for key, value in result.items() if key != "execution_metadata"}
    log = db.get(ModelCallLog, run_id)
    if (log is None or log.status != "success" or log.project_id != access.envelope.scope.project_id
            or log.skill_version_id != access.skill_version_id or log.context_hash != access.envelope.context_hash()
            or log.model_profile_id != access.model_profile_id or log.provider != access.provider
            or not access.expected_model or log.model_name != access.expected_model
            or log.execution_kind not in {"mock_model", "real_model"} or log.output_hash != stable_hash(payload)):
        return None
    recorded = log.execution_metadata_json or {}
    if (recorded.get("is_test") is not False or recorded.get("binding_id") != access.binding_id
            or metadata.get("run_id") != run_id or metadata.get("model_name") != log.model_name
            or metadata.get("execution_kind") != log.execution_kind):
        return None
    try:
        schema = runtime.output_schema(access.envelope.task_key)
        output = schema.model_validate({key: payload[key] for key in schema.model_fields if key in payload})
        runtime.validate_native_output(output, access.envelope)
        for claim in output.claims:
            validate_claim_references(claim, access.envelope)
        for comparison in output.policy_comparisons:
            validate_policy_comparison(comparison, access.envelope)
    except (ValueError, TypeError):
        return None
    return output.model_dump(mode="json"), log


def make_candidate(db, access, result, *, ttl_seconds=60):
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        fail(422, "invalid_cache_ttl")
    if access is None:
        return None
    run_id = result.get("execution_metadata", {}).get("run_id")
    if type(run_id) is not int or _validated_payload(db, access, result, run_id) is None:
        return None
    return CacheCandidate(access.key, deepcopy(result), run_id,
                          datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))


def lookup_lineage_candidate(db, principal, project_id, request, candidate, *, force_refresh=False):
    # Authorization and evidence rebuilding precede even key/TTL checks. This
    # rechecks effective clauses, source versions, classification and model policy.
    access = prepare_lineage_access(db, principal, project_id, request)
    if force_refresh or access is None or candidate is None:
        return None
    if candidate.key != access.key or candidate.expires_at <= datetime.now(timezone.utc):
        return None
    validated = _validated_payload(db, access, candidate.result, candidate.origin_run_id)
    if validated is None:
        return None
    output, log = validated
    return {"candidate": output,
        "facts": [item.model_dump(mode="json") for item in access.envelope.facts],
        "policy_evidence": [item.model_dump(mode="json") for item in access.envelope.policy_evidence],
        "provenance": {"cache_hit": True, "execution_kind": "deterministic",
            "origin_execution_kind": log.execution_kind, "origin_run_id": log.id,
            "actual_model": log.model_name, "skill_version_id": access.skill_version_id,
            "context_hash": access.envelope.context_hash(), "requires_human_confirmation": True}}
