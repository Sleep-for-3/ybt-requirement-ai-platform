"""Explicit, bounded model rerank over one existing field-candidate snapshot.

This module never selects, probes, adopts or writes a mapping.  It re-authorizes and
rebuilds the deterministic recall snapshot before and after the single model call, and it
never relabels a deterministic fallback as a model result: the response always carries the
execution class that actually produced the returned ordering.
"""
import asyncio
import json
import time

from app.schemas.ai_skill import (EvidenceSource, SkillEvidence, SkillInputEnvelope, SkillRunIdentity,
                                 SkillScope)
from app.schemas.ai_skill_ranking import FieldRankingCandidate, RankedCandidate, validate_field_ranking
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
RERANK_MAX_BATCHES = 7
# The batch count is additionally capped by how many finalists one decisive prompt can hold, which
# is itself the measured per-prompt capacity (at most 7 here).  With ``capacity=3`` that allows up
# to 7 batches = 21 candidates in one run, so the shipped ``top_k=20`` recall is fully covered.
RERANK_FINALISTS_PER_BATCH = 2
# One screening call per batch (plus at most one bounded retry each) plus one decisive call.
RERANK_MAX_MODEL_CALLS = 2 * RERANK_MAX_BATCHES + 2
# A candidate that never entered a model batch is still a deterministic recall candidate; these
# labels say which comparison actually placed it instead of implying the model compared everything.
RANK_SOURCE_MODEL = "model"
RANK_SOURCE_BATCH_SCREENED = "batch_screened"
RANK_SOURCE_UNEVALUATED = "recall_unevaluated"
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


def _fact_wire_bytes(fact) -> int:
    """UTF-8 size of one fact exactly as ``compile_input`` serialises it."""

    return len(json.dumps(fact.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))


def _budget_exceeded(exc) -> bool:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return exc.status_code == 409 and detail.get("error_code") == "context_budget_exceeded"


def measure_batch_capacity(db, definition, version, envelope) -> int:
    """How many of this envelope's candidates one compiled prompt can hold.

    The number is *measured* from the compiled budget (``limit`` / ``used``), not guessed: every
    additional fact costs its own serialised bytes plus the JSON array separator, so the capacity
    follows the profile, the output reserve and the protocol reserve instead of a hard-coded 7.
    A final real compile confirms the estimate; redaction can only make a batch smaller, and it can
    never overflow the budget.  A snapshot whose very first candidate does not fit still raises the
    original 409 -- a rerank over nothing is a failure, not a smaller answer.
    """

    facts = list(envelope.facts)
    single = compile_input(db, definition, version,
                           envelope.model_copy(update={"facts": facts[:1]}))
    limit = int(single.budget["limit"])
    used = int(single.budget["used"])
    capacity = 1
    for index, fact in enumerate(facts[1:], start=2):
        used += _fact_wire_bytes(fact) + 1
        if used > limit:
            break
        capacity = index
    while capacity > 1:
        try:
            compile_input(db, definition, version,
                          envelope.model_copy(update={"facts": facts[:capacity]}))
        except Exception as exc:
            from fastapi import HTTPException

            if not isinstance(exc, HTTPException) or not _budget_exceeded(exc):
                raise
            capacity -= 1
            continue
        break
    return capacity


def _select_finalists(leaders_per_batch, capacity: int) -> list[str]:
    """Deterministic finalist subset that one decisive prompt can hold.

    Leaders arrive in batch order, so taking the first ``capacity`` would always drop the tail
    batches' leaders.  Instead every batch's top leader is kept first (round-robin across batches),
    then second leaders, and so on: the selection is a pure function of the batch order and the
    leader ranks, never of any model-reported score, so a re-run over the same snapshot is stable.
    """

    selected: list[str] = []
    rank = 0
    while len(selected) < capacity:
        added = False
        for leaders in leaders_per_batch:
            if rank < len(leaders) and len(selected) < capacity:
                if leaders[rank] not in selected:
                    selected.append(leaders[rank])
                    added = True
        if not added:
            break
        rank += 1
    return selected

def split_batches(envelope, capacity: int) -> list[list]:
    """Consecutive, recall-ordered batches, bounded only by the call/wall-clock ceiling.

    Every recalled candidate is covered as long as ``ceil(len(facts) / capacity) <= RERANK_MAX_BATCHES``;
    the shipped ``top_k=20`` with the smallest observed capacity (3) needs 7 batches, which is exactly
    the ceiling.  A decisive prompt is bounded separately by its own capacity, so a small capacity
    costs finalist breadth, never candidate coverage.
    """

    facts = list(envelope.facts)
    # The batch count is bounded by the call/wall-clock ceiling only.  The decisive prompt is
    # bounded separately: its finalist set is capped at ``capacity`` (see ``_select_finalists``),
    # so a small capacity costs finalist breadth, never candidate coverage.
    limited = RERANK_MAX_BATCHES
    return [facts[start:start + capacity]
            for start in range(0, min(len(facts), capacity * limited), capacity)]


def fit_rerank_envelope(db, definition, version, envelope):
    """Trim the weakest candidates until the compiled prompt fits the model's context budget.

    Kept as the single-prompt view of :func:`measure_batch_capacity`: recall already orders
    candidates strongest first, so only the tail is trimmed and nothing that remains is reordered.
    Returns ``(fitted_envelope, dropped_count)``; a zero count means the envelope already fit.
    """

    capacity = measure_batch_capacity(db, definition, version, envelope)
    fitted = envelope.model_copy(update={"facts": list(envelope.facts)[:capacity]})
    return fitted, len(envelope.facts) - len(fitted.facts)


def candidate_scope(recalled: int, admitted: int) -> dict | None:
    """A visible record of candidate reduction; ``None`` when nothing was dropped.

    Kept narrow on purpose: this field answers only "did the prompt budget force a reduction".
    Whether every candidate was actually compared by the model is a different fact and lives in
    ``rerank.coverage`` so the two can never be confused.
    """

    dropped = recalled - admitted
    if dropped <= 0:
        return None
    return {"recalled": recalled, "admitted": admitted, "dropped_for_context_budget": dropped,
            "reason": "model_context_budget"}


def coverage_info(recall, *, model_evaluated_ids, recall_ordered_ids, admitted=None) -> dict:
    """``recalled / admitted / model_evaluated / returned`` as four independent counts.

    ``unranked_ids`` names every candidate the model never compared, so a caller can never read the
    displayed order as a full model ranking.  ``returned`` equals ``recalled`` because the display
    keeps every recalled candidate: unevaluated ones follow the evaluated ones in recall order.
    ``admitted`` is supplied by the caller (the batches that actually ran); it can be smaller than
    ``recalled`` when the bounded batch count itself caps the scan.
    """

    order = list(recall_ordered_ids)
    evaluated = set(model_evaluated_ids)
    return {
        "recalled": len(order),
        "admitted": len(order) if admitted is None else int(admitted),
        "model_evaluated": len(evaluated & set(order)),
        "returned": len(recall["candidates"]),
        "unranked_ids": [value for value in order if value not in evaluated],
        "coverage": "full" if evaluated >= set(order) else "partial",
    }



def rerank_payload(item, *, score, rationale, evidence_refs, rank_source):
    """Keep the original recall evidence visible next to whatever ordering is displayed."""

    return {**item, "recall_score": item["score"], "recall_rationale": item["rationale"],
            "score": score, "rationale": rationale, "evidence_refs": list(evidence_refs), "rank_source": rank_source}


def fallback_response(recall, *, error_code, provenance, model_metadata, snapshot_recheck,
                      candidate_scope_info=None, coverage=None):
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
                       "candidate_scope": candidate_scope_info, "coverage": coverage,
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


def _ordered_display(recall, ranking, *, finalists, batch_screened, evaluated):
    """Evaluate first, then recall order; the model's own scores only order the finalists.

    ``ranking`` is the decisive call's permutation of ``finalists``.  Batch-screened candidates
    that lost a finalist slot, and candidates that never entered a batch at all, keep the
    deterministic recall order *after* the finalists.  Scores from different batches are never
    compared against each other: only the single decisive call may place one above another.
    """

    allowed = {item["candidate_id"]: item for item in recall["candidates"]}
    recalled_order = [item["candidate_id"] for item in recall["candidates"]]
    position = {value: index for index, value in enumerate(recalled_order)}
    by_finalist = {item.candidate_id: item for item in ranking.ranking}
    ordered = []
    # Within the one decisive call the scores ARE comparable, so the finalists are ordered by that
    # call's own ranking (score desc, then ordinal) — the same rule the original single-call path
    # used. Only cross-batch placement is forbidden.
    for item in sorted(ranking.ranking, key=lambda entry: (-entry.score, candidate_ordinal(entry.candidate_id))):
        if item.candidate_id not in allowed:
            continue
        ordered.append(rerank_payload(allowed[item.candidate_id], score=float(item.score),
                                      rationale=item.rationale, evidence_refs=item.evidence_refs,
                                      rank_source=RANK_SOURCE_MODEL))
    screened = set(batch_screened) - set(finalists)
    for candidate_id in recalled_order:
        if candidate_id in considered_ids(finalists):
            continue
        source = RANK_SOURCE_BATCH_SCREENED if candidate_id in screened else RANK_SOURCE_UNEVALUATED
        item = allowed[candidate_id]
        note = ("本批内已由模型比较，但未进入决赛集合；按召回顺序列出" if source == RANK_SOURCE_BATCH_SCREENED
                else "未进入任何模型比较批次；保留召回顺序，未由模型评估")
        ordered.append(rerank_payload(item, score=item["score"], rationale=f"{item['rationale']}（{note}）",
                                      evidence_refs=[], rank_source=source))
    # Only the finalists may be reordered by the model: ``ordered`` was built finalist-first in the
    # decisive ranking order, then the rest in canonical recall order.  Re-sorting here would
    # silently throw the model's placement away.
    return ordered


def considered_ids(finalists):
    """Alias kept tiny on purpose: the finalist set is the only model-comparable group."""

    return set(finalists)


def applied_response(recall, ranking, *, provenance, model_metadata, candidate_scope_info=None,
                     finalists=None, batch_screened=None, evaluated=None, coverage=None):
    finalists = list(finalists if finalists is not None
                     else [item.candidate_id for item in ranking.ranking])
    batch_screened = list(batch_screened or finalists)
    evaluated = set(evaluated if evaluated is not None else finalists)
    ordered = _ordered_display(recall, ranking, finalists=finalists, batch_screened=batch_screened,
                               evaluated=evaluated)
    return {"context_hash": recall["context_hash"],
            "candidates": ordered,
            "scanned_count": recall["scanned_count"], "returned_count": recall["returned_count"],
            "requires_human_confirmation": True, "writes_mapping": False,
            "ranking_mode": "model_rerank", "execution_metadata": model_metadata,
            "rerank": {"status": "applied", "error_code": None, "message": APPLIED_MESSAGE,
                       "snapshot_recheck": "unchanged", "run_id": model_metadata.get("run_id"),
                       "candidate_scope": candidate_scope_info, "coverage": coverage,
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
    # Recall returns ``top_k`` (20 by default) candidates while the shipped profile fits only a
    # handful in one prompt.  Dropping the tail used to mean the model never compared a correct
    # candidate sitting at position 8/15/20, so the whole recall list is now compared in bounded
    # batches and one decisive call ranks the per-batch leaders.  Nothing is silently promoted and
    # nothing unevaluated is labelled as evaluated.
    capacity = measure_batch_capacity(db, definition, version, envelope)
    batches = split_batches(envelope, capacity)
    recall_ids = [item["candidate_id"] for item in current["candidates"]]
    admitted = sum(len(batch) for batch in batches)
    batch_screened: list[str] = []
    batch_metadatas: list[dict] = []
    batch_rankings: list = []
    leaders_per_batch: list[list] = []
    finalists: list[str] = []
    screened_scores: dict[str, float] = {}
    metadata_calls = 0
    tokens_reported = 0
    wall_started = time.perf_counter()
    # The budget is opt-in: ``0`` (the shipped default) keeps the historical "wait for the model"
    # behaviour, so no existing caller changes outcome until a human adopts degrade-instead-of-block.
    budget = rerank_timeout_seconds()

    def _parse_ranking(payload, scope_envelope):
        body = payload.get("candidate")
        if not isinstance(body, dict):
            return None
        try:
            parsed = FieldRankingCandidate(ranking=body.get("ranking") or [])
            validate_field_ranking(parsed, scope_envelope)
            return parsed
        except Exception:
            return None

    async def _call_once(call_envelope):
        """One bounded model call; ``(result, expired, attempts)`` and no raise on expiry."""

        calls = 0
        while True:
            calls += 1
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    execute_resolved(db, call_envelope, definition, version, binding),
                    timeout=budget or None)
                expired = False
            except (asyncio.TimeoutError, TimeoutError):
                # The cancelled attempt never reaches its own log call, so log the expiry here.
                result = {"execution_metadata": _timeout_metadata(
                    db, call_envelope, definition, version, binding, budget, started)}
                expired = True
            metadata = dict(result.get("execution_metadata") or {})
            ranking = _parse_ranking(result, call_envelope)
            # Bounded, audited retry for the one observed failure mode: the provider answers HTTP 200
            # with an empty/invalid ranking. An expiry is never retried (see RERANK_TIMEOUT_CODE).
            retryable = (not expired and ranking is None and calls < MAX_RERANK_ATTEMPTS
                         and metadata.get("degraded_reason") in RETRYABLE_MODEL_FAILURES)
            if not retryable:
                return result, expired, ranking, calls, metadata
    if not batches:
        # Every candidate individually overflows the prompt: this is a refusal, not an empty rank.
        fail(409, "context_budget_exceeded")
    degraded = None
    for index, batch in enumerate(batches):
        call_envelope = envelope.model_copy(update={"facts": batch})
        result, expired, ranking, calls, metadata = await _call_once(call_envelope)
        metadata_calls += calls
        token_usage = (metadata.get("token_usage") or {})
        tokens_reported += int(token_usage.get("total_tokens") or 0)
        batch_metadatas.append(metadata)
        if expired:
            degraded = (RERANK_TIMEOUT_CODE, metadata)
            break
        if ranking is None:
            degraded = (metadata.get("degraded_reason") or "model_output_unavailable", metadata)
            break
        batch_screened.extend(item.id for item in batch)
        leaders = [item.candidate_id for item in
                   sorted(ranking.ranking, key=lambda entry: (-entry.score, candidate_ordinal(entry.candidate_id)))
                   ][:RERANK_FINALISTS_PER_BATCH]
        leaders_per_batch.append(leaders)
        screened_scores.update({entry.candidate_id: float(entry.score) for entry in ranking.ranking})
        batch_rankings.append(ranking)
    decisive_metadata = batch_metadatas[-1] if batch_metadatas else None
    decisive = None
    if degraded is not None:
        pass
    elif len(batches) == 1:
        # One batch already compared every admitted candidate in a single prompt: its ranking *is*
        # the decisive ranking, so a second call would only re-ask the same question.
        decisive = batch_rankings[0]
        finalists = [item.candidate_id for item in decisive.ranking]
    else:
        # Only what fits one decisive prompt: the finalist set is capped by the measured capacity
        # and chosen round-robin across batches, so a small capacity costs finalist breadth only.
        finalists = _select_finalists(leaders_per_batch, capacity)
        if len(finalists) > 1:
            # One decisive call over the calibration-free finalist set only: scores from different
            # batches are never compared against each other, so the model's global ordering here is
            # the only cross-batch comparison that happens.
            finalist_ids = set(finalists)
            finalist_facts = [fact for fact in envelope.facts if fact.id in finalist_ids]
            call_envelope = envelope.model_copy(update={"facts": finalist_facts})
            result, expired, ranking, calls, metadata = await _call_once(call_envelope)
            metadata_calls += calls
            tokens_reported += int((metadata.get("token_usage") or {}).get("total_tokens") or 0)
            decisive_metadata = metadata
            if expired:
                degraded = (RERANK_TIMEOUT_CODE, metadata)
            elif ranking is None:
                degraded = (metadata.get("degraded_reason") or "model_output_unavailable", metadata)
            else:
                decisive = ranking
                finalists = [item.candidate_id for item in ranking.ranking]
        elif len(finalists) == 1:
            # A single finalist needs no decisive call: it is already the only model-placed candidate.
            only = finalists[0]
            decisive = FieldRankingCandidate(ranking=[RankedCandidate(
                candidate_id=only, score=max(0.0, min(1.0, screened_scores.get(only, 0.0))),
                rationale="该候选是其所在批次的模型首位，无需额外决赛调用（未跨批比较）。",
                evidence_refs=[only])])
    coverage = coverage_info(current, model_evaluated_ids=batch_screened,
                            recall_ordered_ids=recall_ids, admitted=admitted)
    scope_info = candidate_scope(len(current["candidates"]), admitted)
    wall_seconds = round(time.perf_counter() - wall_started, 3)
    if decisive_metadata is not None:
        model_metadata = dict(decisive_metadata)
    elif degraded is not None:
        model_metadata = dict(degraded[1])
    elif batch_metadatas:
        model_metadata = dict(batch_metadatas[0])
    else:
        model_metadata = {}
    model_metadata.update({
        "rerank_attempts": metadata_calls,
        "rerank_model_calls": metadata_calls,
        "rerank_batch_capacity": capacity,
        "rerank_batch_count": len(batches),
        "rerank_finalists": len(finalists),
        "rerank_max_model_calls": RERANK_MAX_MODEL_CALLS,
        "rerank_tokens_reported": tokens_reported,
        "rerank_wall_seconds": wall_seconds,
        "rerank_wall_budget_seconds": budget * RERANK_MAX_MODEL_CALLS if budget else None,
        "rerank_coverage": coverage["coverage"],
        "token_usage": {"usage_available": bool(tokens_reported), "total_tokens": tokens_reported},
    })
    if degraded is not None or decisive is None:
        model_metadata["degraded_reason"] = degraded[0] if degraded else "model_output_unavailable"
    # Post-call recheck: a revoked permission still raises, and it wins over any model output.
    recheck = recall_fields(db, principal, payload.input)
    changed = recheck["context_hash"] != current["context_hash"]
    if degraded is not None or decisive is None or changed:
        return fallback_response(recheck if changed else current,
                                 error_code="candidate_snapshot_changed_after_call" if changed
                                 else (degraded[0] if degraded else "model_output_unavailable"),
                                 provenance=provenance, model_metadata=model_metadata,
                                 snapshot_recheck="changed_after_call" if changed else "unchanged",
                                 candidate_scope_info=scope_info, coverage=coverage)
    return applied_response(current, decisive, provenance=provenance, model_metadata=model_metadata,
                            candidate_scope_info=scope_info, finalists=finalists,
                            batch_screened=batch_screened, evaluated=batch_screened,
                            coverage=coverage)
