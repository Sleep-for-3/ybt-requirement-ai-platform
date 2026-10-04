"""Explicit, bounded model rerank over one existing field-candidate snapshot.

This module never selects, probes, adopts or writes a mapping.  It re-authorizes and
rebuilds the deterministic recall snapshot before and after the single model call, and it
never relabels a deterministic fallback as a model result: the response always carries the
execution class that actually produced the returned ordering.
"""
from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillInputEnvelope, SkillScope
from app.schemas.ai_skill_ranking import FieldRankingCandidate, validate_field_ranking
from app.services.ai_skills.control import fail
from app.services.ai_skills.field_candidates import recall_fields
from app.services.ai_skills.runtime import FIELD_RERANK_TASK, execute_resolved, resolve_skill
from app.services.auth.permission_service import PermissionService
from app.services.llm.execution_metadata import deterministic_execution_metadata

RERANK_MAX_CANDIDATES = 50
RERANK_MAX_INPUT_BYTES = 32000
LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
FALLBACK_MESSAGE = "未获得通过校验的模型重排结果，以下仍为确定性召回排序；本次不代表模型成功。"
APPLIED_MESSAGE = "已按固定发布 Skill 的模型输出重排；分数为排序值而非业务置信度，选择、探查与采用仍需人工完成。"


# One bounded retry for an explicitly invalid model response; the attempt count is always reported.
MAX_RERANK_ATTEMPTS = 2
RETRYABLE_MODEL_FAILURES = {"invalid_model_response"}
_VALUE_FIELDS = ("database_name", "schema_name", "table_name", "column_name", "column_comment",
                 "table_comment", "data_type", "nullable", "source_version")


def confidentiality_floor(project) -> str:
    """Catalog structure stays sensitive: cloud providers are denied unless it is local/Mock.

    An unknown or missing project classification is treated as ``restricted`` rather than
    silently downgraded. The rule itself now lives in the single outbound gateway
    (``app.services.security.outbound_policy``) so the rerank and prompt paths cannot drift apart;
    this wrapper keeps the historical name for existing callers and tests.
    """

    from app.services.security.outbound_policy import catalog_confidentiality_floor

    return catalog_confidentiality_floor(project)


def _outbound_authorized_project_ids() -> set[str]:
    from app.services.security.outbound_policy import outbound_authorized_project_ids

    return outbound_authorized_project_ids()


def build_rerank_envelope(project, scope: SkillScope, target_field_id: int, recall: dict):
    """Bound the model input to the recall whitelist; return ``(envelope, block_code)``.

    Only catalog metadata travels: never a connection string, host, port, username,
    credential or a single source-database row.
    """

    candidates = recall["candidates"]
    if not candidates:
        return None, "no_candidates_to_rerank"
    if len(candidates) > RERANK_MAX_CANDIDATES:
        return None, "candidate_scope_too_large"
    level = confidentiality_floor(project)
    facts = []
    for item in candidates:
        locator = ".".join(filter(None, (item.get("database_name"), item.get("schema_name"), item.get("table_name"),
                                         item.get("column_name"))))[:255] or item["candidate_id"]
        facts.append(SkillEvidence(
            id=item["candidate_id"], kind="catalog_field",
            value={**{key: item.get(key) for key in _VALUE_FIELDS},
                   "recall_score": item["score"], "recall_rationale": item["rationale"]},
            source=EvidenceSource(source_type="catalog_column", source_id=str(item["catalog_column_id"]),
                                  source_version=item["source_version"], locator=locator, scope=scope),
            confidentiality=level))
    envelope = SkillInputEnvelope(skill_key=FIELD_RERANK_TASK, task_key=FIELD_RERANK_TASK, scope=scope,
                                  subject_ref=f"field_candidates:{target_field_id}:{recall['context_hash'][:16]}",
                                  facts=facts, max_input_bytes=RERANK_MAX_INPUT_BYTES)
    return envelope, None


def rerank_payload(item, *, score, rationale, evidence_refs, rank_source):
    """Keep the original recall evidence visible next to whatever ordering is displayed."""

    return {**item, "recall_score": item["score"], "recall_rationale": item["rationale"],
            "score": score, "rationale": rationale, "evidence_refs": list(evidence_refs), "rank_source": rank_source}


def fallback_response(recall, *, error_code, provenance, model_metadata, snapshot_recheck):
    return {"context_hash": recall["context_hash"],
            "candidates": [rerank_payload(item, score=item["score"], rationale=item["rationale"],
                                          evidence_refs=[], rank_source="recall")
                           for item in recall["candidates"]],
            "scanned_count": recall["scanned_count"], "returned_count": recall["returned_count"],
            "requires_human_confirmation": True, "writes_mapping": False,
            "ranking_mode": "deterministic_recall",
            "execution_metadata": deterministic_execution_metadata("field_candidate_recall",
                                                                   context_hash=recall["context_hash"]),
            "rerank": {"status": "failed", "error_code": error_code, "message": FALLBACK_MESSAGE,
                       "snapshot_recheck": snapshot_recheck, "run_id": (model_metadata or {}).get("run_id"),
                       "model_metadata": model_metadata, **provenance}}


UNRANKED_ORDINAL = 1 << 30


def candidate_ordinal(candidate_id: str) -> int:
    """Deterministic tie-break for ranking display; ids without the ``catalog:<n>`` shape sort last
    instead of raising, so a malformed proposal is rejected by validation rather than by a crash."""
    prefix, separator, suffix = candidate_id.partition(":")
    return int(suffix) if separator and suffix.isdigit() else UNRANKED_ORDINAL


def applied_response(recall, ranking, *, provenance, model_metadata):
    allowed = {item["candidate_id"]: item for item in recall["candidates"]}
    ordered = sorted(ranking.ranking, key=lambda item: (-item.score, candidate_ordinal(item.candidate_id)))
    return {"context_hash": recall["context_hash"],
            "candidates": [rerank_payload(allowed[item.candidate_id], score=float(item.score),
                                          rationale=item.rationale, evidence_refs=item.evidence_refs,
                                          rank_source="model") for item in ordered],
            "scanned_count": recall["scanned_count"], "returned_count": recall["returned_count"],
            "requires_human_confirmation": True, "writes_mapping": False,
            "ranking_mode": "model_rerank", "execution_metadata": model_metadata,
            "rerank": {"status": "applied", "error_code": None, "message": APPLIED_MESSAGE,
                       "snapshot_recheck": "unchanged", "run_id": model_metadata.get("run_id"),
                       "model_metadata": model_metadata, **provenance}}


def _provenance(definition, version, binding):
    return {"skill_key": definition.skill_key,
            "skill_version": {"id": version.id, "version_no": version.version_no, "content_hash": version.content_hash},
            "binding_scope": binding.scope_key}


async def rerank_fields(db, principal, payload):
    """Rerank one authorized snapshot; fall back explicitly instead of faking a model result."""

    current = recall_fields(db, principal, payload.input)
    if current["context_hash"] != payload.context_hash:
        fail(409, "candidate_snapshot_changed")
    project = PermissionService(db, principal).require_project_permission(payload.input.project_id, "technical.edit")
    if project.institution_id is None:
        fail(409, "project_institution_required")
    scope = SkillScope(scope_type="project", institution_id=project.institution_id, project_id=project.id)
    resolved = resolve_skill(db, principal, FIELD_RERANK_TASK, scope)
    if resolved is None:
        # Never fall back to a Legacy prompt or to deterministic pseudo-success.
        fail(409, "skill_binding_required")
    definition, version, binding = resolved
    provenance = _provenance(definition, version, binding)
    envelope, blocked = build_rerank_envelope(project, scope, payload.input.target_field_id, current)
    if blocked == "no_candidates_to_rerank":
        return fallback_response(current, error_code=blocked, provenance=provenance,
                                 model_metadata=None, snapshot_recheck="unchanged")
    if blocked:
        fail(409, blocked)
    def _parse_ranking(payload):
        body = payload.get("candidate")
        if not isinstance(body, dict):
            return None
        try:
            parsed = FieldRankingCandidate(ranking=body.get("ranking") or [])
            validate_field_ranking(parsed, envelope)
            return parsed
        except Exception:
            return None

    result = await execute_resolved(db, envelope, definition, version, binding)
    model_metadata = dict(result.get("execution_metadata") or {})
    ranking = _parse_ranking(result)
    attempts = 1
    # Bounded, audited retry for the one observed failure mode: the provider answers HTTP 200 with
    # an empty/invalid ranking (invalid_model_response). One extra attempt only, never on policy
    # denials or provider outages, and the attempt count is reported in the response metadata.
    while ranking is None and attempts < MAX_RERANK_ATTEMPTS and model_metadata.get("degraded_reason") in RETRYABLE_MODEL_FAILURES:
        result = await execute_resolved(db, envelope, definition, version, binding)
        model_metadata = dict(result.get("execution_metadata") or {})
        ranking = _parse_ranking(result)
        attempts += 1
    model_metadata["rerank_attempts"] = attempts
    failure_code = None if ranking is not None else (model_metadata.get("degraded_reason") or "model_output_unavailable")
    # Post-call recheck: a revoked permission still raises, and it wins over any model output.
    recheck = recall_fields(db, principal, payload.input)
    changed = recheck["context_hash"] != current["context_hash"]
    if failure_code is not None or changed:
        return fallback_response(recheck if changed else current,
                                 error_code="candidate_snapshot_changed_after_call" if changed else failure_code,
                                 provenance=provenance, model_metadata=model_metadata,
                                 snapshot_recheck="changed_after_call" if changed else "unchanged")
    return applied_response(current, ranking, provenance=provenance, model_metadata=model_metadata)
