"""Explicit, bounded model rerank over one existing field-candidate snapshot.

This module never selects, probes, adopts or writes a mapping.  It re-authorizes and
rebuilds the deterministic recall snapshot before and after the single model call, and it
never relabels a deterministic fallback as a model result: the response always carries the
execution class that actually produced the returned ordering.
"""
import asyncio
import time

from app.schemas.ai_skill import (EvidenceSource, SkillEvidence, SkillInputEnvelope, SkillRunIdentity,
                                 SkillScope)
from app.schemas.ai_skill_ranking import FieldRankingCandidate, validate_field_ranking
from app.services.ai_skills.control import fail
from app.services.ai_skills.field_candidates import recall_fields
from app.services.ai_skills.runtime import FIELD_RERANK_TASK, compile_input, execute_resolved, resolve_skill
from app.services.auth.permission_service import PermissionService
from app.services.llm.execution_metadata import build_execution_metadata, deterministic_execution_metadata
from app.services.llm.prompt_runtime import record_model_call

RERANK_MAX_CANDIDATES = 50
RERANK_MAX_INPUT_BYTES = 32000
LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
FALLBACK_MESSAGE = "未获得通过校验的模型重排结果，以下仍为确定性召回排序；本次不代表模型成功。"
APPLIED_MESSAGE = "已按固定发布 Skill 的模型输出重排；分数为排序值而非业务置信度，选择、探查与采用仍需人工完成。"


# One bounded retry for an explicitly invalid model response; the attempt count is always reported.
MAX_RERANK_ATTEMPTS = 2
RETRYABLE_MODEL_FAILURES = {"invalid_model_response"}
# A budget expiry is deliberately NOT retryable: a second attempt would double the wall-clock the
# user already paid for a call the product contract says must answer or degrade explicitly.
RERANK_TIMEOUT_CODE = "rerank_timeout"
MIN_RERANK_CANDIDATES = 1
# Only differentiated descriptor content travels.  A key whose value is absent carries nothing the
# model could use, and ``source_version`` is the digest of this very descriptor and already travels
# verbatim on ``source.source_version``, so shipping it inside ``value`` charges the model context
# budget twice for one identifier.  Dropping both is lossless; nothing is inferred.
_VALUE_FIELDS = ("database_name", "schema_name", "table_name", "column_name", "column_comment",
                 "table_comment", "data_type", "nullable")


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

def _descriptor_value(item) -> dict:
    """The candidate's own descriptor, minus anything that is absent or repeated elsewhere.

    Only the model reads this; recall keeps the untrimmed material for its response.
    """

    return {key: item[key] for key in _VALUE_FIELDS
            if item.get(key) is not None and item.get(key) != ""}

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
            value={**_descriptor_value(item),
                   "recall_score": item["score"], "recall_rationale": item["rationale"]},
            source=EvidenceSource(source_type="catalog_column", source_id=str(item["catalog_column_id"]),
                                  source_version=item["source_version"], locator=locator, scope=scope),
            confidentiality=level))
    envelope = SkillInputEnvelope(skill_key=FIELD_RERANK_TASK, task_key=FIELD_RERANK_TASK, scope=scope,
                                  subject_ref=f"field_candidates:{target_field_id}:{recall['context_hash'][:16]}",
                                  facts=facts, max_input_bytes=RERANK_MAX_INPUT_BYTES)
    return envelope, None


def fit_rerank_envelope(db, definition, version, envelope):
    """Trim the weakest candidates until the compiled prompt fits the model's context budget.

    Recall already orders candidates strongest first, so dropping from the tail keeps the best
    ones and never reorders what remains.  Returns ``(fitted_envelope, dropped_count)``; a zero
    count means the envelope was already inside the budget and is returned untouched.

    Refusing outright when even ``MIN_RERANK_CANDIDATES`` do not fit is deliberate: a rerank over
    nothing is not a smaller answer, it is a failure, and the caller still turns that into an
    explicit 409 rather than a silent empty ranking.
    """

    from fastapi import HTTPException

    from app.services.ai_skills.runtime import compile_input

    facts = list(envelope.facts)
    while True:
        fitted = envelope.model_copy(update={"facts": facts})
        try:
            compile_input(db, definition, version, fitted)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            too_large = exc.status_code == 409 and detail.get("error_code") == "context_budget_exceeded"
            if not too_large or len(facts) <= MIN_RERANK_CANDIDATES:
                raise
            facts = facts[:-1]
            continue
        return fitted, len(envelope.facts) - len(facts)


def candidate_scope(recalled: int, admitted: int) -> dict | None:
    """A visible record of candidate reduction; ``None`` when nothing was dropped."""

    dropped = recalled - admitted
    if dropped <= 0:
        return None
    return {"recalled": recalled, "admitted": admitted, "dropped_for_context_budget": dropped,
            "reason": "model_context_budget"}


def rerank_payload(item, *, score, rationale, evidence_refs, rank_source):
    """Keep the original recall evidence visible next to whatever ordering is displayed."""

    return {**item, "recall_score": item["score"], "recall_rationale": item["rationale"],
            "score": score, "rationale": rationale, "evidence_refs": list(evidence_refs), "rank_source": rank_source}


def fallback_response(recall, *, error_code, provenance, model_metadata, snapshot_recheck,
                      candidate_scope_info=None):
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
                       "candidate_scope": candidate_scope_info,
                       "model_metadata": model_metadata, **provenance}}

UNRANKED_ORDINAL = 1 << 30


def candidate_ordinal(candidate_id: str) -> int:
    """Deterministic tie-break for ranking display; ids without the ``catalog:<n>`` shape sort last
    instead of raising, so a malformed proposal is rejected by validation rather than by a crash."""
    prefix, separator, suffix = candidate_id.partition(":")
    return int(suffix) if separator and suffix.isdigit() else UNRANKED_ORDINAL


def rerank_timeout_seconds() -> float:
    """Wall-clock budget for one rerank model call; ``0`` keeps the unbounded wait.

    ``0`` is the shipped default because answering with the deterministic recall order when the
    model is merely slow changes a user-visible product outcome: whether that trade is acceptable
    is a human decision, not a code default.  A configured value is bounded by settings validation.
    """

    from app.core.settings import get_settings

    value = float(getattr(get_settings(), "field_rerank_timeout_seconds", 0) or 0)
    return value if value >= 1 else 0.0


def _timeout_metadata(db, envelope, definition, version, binding, budget, started) -> dict:
    """Keep an expired budget auditable: the model call happened, it just never answered.

    The cancelled attempt cannot log itself (``asyncio.wait_for`` aborts it before it reaches
    ``record_model_call``), so the degraded run writes the same shape of record here instead of
    leaving the slowest, most expensive path out of the audit trail.
    """

    compiled = compile_input(db, definition, version, envelope)
    metadata = build_execution_metadata(compiled.runtime, execution_kind="degraded",
                                        context_hash=compiled.context_hash, context_budget=compiled.budget,
                                        context_complete=not envelope.gaps, degraded_reason=RERANK_TIMEOUT_CODE)
    metadata.update(SkillRunIdentity(runtime_mode="skill", execution_kind=metadata["execution_kind"],
                                     skill_key=definition.skill_key, skill_version_id=version.id,
                                     skill_version_no=version.version_no,
                                     input_contract_version=envelope.input_contract_version,
                                     context_hash=compiled.context_hash).model_dump(mode="json"))
    metadata.update({"skill_version": f"v{version.version_no}", "binding_id": binding.id if binding else None,
                     "binding_scope": binding.scope_key if binding else None,
                     "content_hash": version.content_hash, "is_test": binding is None,
                     "rerank_timeout_seconds": budget})
    log = record_model_call(db, envelope.scope.project_id, compiled.runtime, compiled.input_text, {"gaps": []},
                            status="failed", started=started, service=None,
                            confidentiality=compiled.confidentiality, execution_metadata=metadata,
                            error_type=RERANK_TIMEOUT_CODE)
    db.flush()
    metadata["run_id"] = log.id
    log.execution_metadata_json = {**metadata}
    return metadata


def applied_response(recall, ranking, *, provenance, model_metadata, candidate_scope_info=None):
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
                       "candidate_scope": candidate_scope_info,
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
    # Recall returns ``top_k`` (20 by default) candidates while the default model profile fits
    # only a handful, so the admission decision has to happen here rather than inside the model
    # call: the weakest tail is dropped before anything is sent, and the drop is reported back.
    envelope, _dropped = fit_rerank_envelope(db, definition, version, envelope)
    scope_info = candidate_scope(len(current["candidates"]), len(envelope.facts))
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
    # The budget is opt-in: ``0`` (the shipped default) keeps the historical "wait for the model"
    # behaviour, so no existing caller changes outcome until a human adopts degrade-instead-of-block.
    budget = rerank_timeout_seconds()

    async def _execute_once():
        """One model call; ``(result, expired)`` and no raise when the budget expires."""

        if not budget:
            return await execute_resolved(db, envelope, definition, version, binding), False
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(
                execute_resolved(db, envelope, definition, version, binding), timeout=budget), False
        except (asyncio.TimeoutError, TimeoutError):
            # The cancelled attempt never reaches its own log call, so log the expiry here.
            metadata = _timeout_metadata(db, envelope, definition, version, binding, budget, started)
            return {"execution_metadata": metadata}, True

    result, expired = await _execute_once()
    model_metadata = dict(result.get("execution_metadata") or {})
    ranking = _parse_ranking(result)
    attempts = 1
    # Bounded, audited retry for the one observed failure mode: the provider answers HTTP 200 with
    # an empty/invalid ranking (invalid_model_response). One extra attempt only, never on policy
    # denials or provider outages, and the attempt count is reported in the response metadata.
    while (not expired and ranking is None and attempts < MAX_RERANK_ATTEMPTS
           and model_metadata.get("degraded_reason") in RETRYABLE_MODEL_FAILURES):
        # Each attempt gets its own budget; an expiry is not retried (see RERANK_TIMEOUT_CODE).
        result, expired = await _execute_once()
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
                                 snapshot_recheck="changed_after_call" if changed else "unchanged",
                                 candidate_scope_info=scope_info)
    return applied_response(current, ranking, provenance=provenance, model_metadata=model_metadata,
                            candidate_scope_info=scope_info)
