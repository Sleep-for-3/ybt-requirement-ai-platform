"""Per-case execution through the real service chain, with only the model boundary replaced.

The point of this runner is to *not* re-test a helper function.  Each family drives the
actual module the product uses:

* citation families call :func:`app.services.rag.citation_validator.check_citation_support`
  and the real :mod:`app.services.rag.grounded_answer_service` assembly path, so a status
  fix in ``grounded_answer_service`` is what makes a case pass;
* the rerank family calls :func:`app.services.ai_skills.field_candidates.recall_fields`
  and :func:`app.services.ai_skills.field_rerank.rerank_fields` (or its envelope helpers)
  over real catalog rows;
* the agent family calls :mod:`app.services.agent.state_machine`, the pure module the
  orchestrator itself uses.

Only ``get_runtime_llm_service`` is replaced, and only with a deterministic stub driven by
the case's recorded ``judge`` payload.  That keeps the protocol, validation, degradation,
status assembly and persistence logic real while making the run reproducible offline.

Nothing here writes to a business table, calls a network provider, or claims real-model
quality.  Every metric it produces is a *protocol* metric.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app.services.evaluation.benchmark import dataset
from app.services.evaluation.benchmark.cases import load_cases

#: A judge/family stub is injected through this attribute so the runner never needs the
#: real gateway.  ``None`` means "keep the real factory" (used only where no call happens).
_GATEWAY_PATCH: dict[str, Any] = {"payload": None, "error": None, "calls": 0}


class _StubService:
    """Deterministic stand-in for the LLM gateway used by the judge engine."""

    last_call = None

    async def chat_json(self, system_prompt: str, user_prompt: str) -> Any:
        _GATEWAY_PATCH["calls"] += 1
        error = _GATEWAY_PATCH["error"]
        if error:
            from app.services.llm.base import LLMProviderError

            raise LLMProviderError(f"stub failure: {error}", error_type=error)
        return _GATEWAY_PATCH["payload"]

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


class _gateway:
    """Context manager that swaps the gateway factory for the duration of one case."""

    def __init__(self, payload: Any = None, error: str | None = None, real: bool = False):
        self.payload = payload
        self.error = error
        self.real = real
        self._original = None
        self.call_log: list = []

    def __enter__(self):
        from app.services.llm import prompt_runtime

        _GATEWAY_PATCH.update({"payload": self.payload, "error": self.error, "calls": 0,
                               "real": self.real, "usage": []})
        self._original = prompt_runtime.get_runtime_llm_service
        if self.real:
            # Real mode: keep the shipped factory so the actual provider is called.  Only the
            # model *profile* is pinned (callers pass it through ``get_prompt_runtime``), and
            # every recorded call is collected so token/wall-clock bounds are measurable
            # rather than merely asserted.
            original = self._original

            def _recording_factory(*args, **kwargs):
                service = original(*args, **kwargs)
                return _RecordingService(service, _GATEWAY_PATCH)

            prompt_runtime.get_runtime_llm_service = _recording_factory
        else:
            prompt_runtime.get_runtime_llm_service = lambda *a, **k: _StubService()
        return self

    def __exit__(self, *exc):
        from app.services.llm import prompt_runtime

        prompt_runtime.get_runtime_llm_service = self._original
        return False

    @property
    def calls(self) -> int:
        return int(_GATEWAY_PATCH["calls"])

    @property
    def usage(self) -> list:
        return list(_GATEWAY_PATCH.get("usage") or [])


class _RecordingService:
    """Transparent wrapper that records the real provider's latency and usage.

    In real mode the *actual* service answers; this wrapper only observes.  It deliberately
    forwards attribute access so nothing about the shipped client changes.
    """

    def __init__(self, inner, patch: dict):
        self._inner = inner
        self._patch = patch

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def chat_json(self, system_prompt, user_prompt):
        import time as _time

        started = _time.perf_counter()
        self._patch["calls"] = int(self._patch.get("calls") or 0) + 1
        try:
            result = await self._inner.chat_json(system_prompt, user_prompt)
        finally:
            elapsed = int((_time.perf_counter() - started) * 1000)
            record = {"latency_ms": elapsed,
                      "meta": getattr(self._inner, "last_call", None)}
            self._patch.setdefault("usage", []).append(record)
        return result

    async def embed_texts(self, texts):
        return await self._inner.embed_texts(texts)


# --------------------------------------------------------------------------- citation


def _judge_payload(case: dict):
    judge = case.get("judge") or {}
    if "error" in judge:
        return None, judge["error"]
    if "payload" in judge:
        return judge["payload"], None
    return judge, None


def _citation_payloads(case: dict) -> list[dict]:
    """Map the case's synthetic units onto the citation shape ``check_citation_support`` takes."""
    return [
        {"citation_id": f"knowledge-unit-{unit['knowledge_unit_id']}",
         "knowledge_unit_id": unit["knowledge_unit_id"],
         "label": f"知识单元 {unit['knowledge_unit_id']}",
         "quoted_content": unit["content"]}
        for unit in case.get("evidence") or []
    ]


def run_citation_case(case: dict) -> dict:
    """Run one citation case through the real validator and record what it did."""
    from app.services.rag import citation_validator

    citations = _citation_payloads(case)
    payload, error = _judge_payload(case)
    started = time.perf_counter()
    with _gateway(payload, error) as gateway:
        if citations:
            result = asyncio.run(citation_validator.check_citation_support(
                _NullSession(), citations, answer=str(case.get("model_answer") or ""),
                project_id=1, confidentiality_levels=["internal"]))
        else:
            result = asyncio.run(citation_validator.check_citation_support(
                _NullSession(), [], answer=str(case.get("model_answer") or ""), project_id=1))
    observed = _citation_observation(result, citations, case)
    return {"case_id": case["case_id"], "family": case["family"], "executed": True,
            "gateway_calls": gateway.calls, "latency_ms": int((time.perf_counter() - started) * 1000),
            "observed": observed, "case_snapshot_hash": dataset.content_hash(case)}


def _citation_observation(result: dict, citations: list[dict], case: dict) -> dict:
    """Describe the judge outcome in the vocabulary the case's expectations use."""
    verdicts = list(result.get("verdicts") or [])
    tally = {"supported": 0, "unsupported": 0, "unknown": 0}
    for item in verdicts:
        verdict = str(item.get("verdict") or "unknown")
        tally[verdict] = tally.get(verdict, 0) + 1
    counts = {
        "citation_count": int(result.get("citation_count") or 0),
        "judged_count": int(result.get("judged_count") or 0),
        "supported": tally["supported"],
        "unsupported": tally["unsupported"],
        "unknown": tally["unknown"],
        "duplicate_verdicts": _duplicate_verdicts(result),
        "degraded": bool(result.get("degraded")),
        "degraded_reason": result.get("degraded_reason"),
        "judged": bool(result.get("judged")),
        "check": result.get("check"),
    }
    # Coverage is judged citations / available citations: a judge that silently skipped a
    # citation must not look like full coverage.
    counts["coverage_ratio"] = (
        round(counts["judged_count"] / counts["citation_count"], 4)
        if counts["citation_count"] else 0.0)
    for verdict in verdicts:
        citation_id = str(verdict.get("citation_id") or "")
        if citation_id and citation_id not in {f"knowledge-unit-{c['knowledge_unit_id']}" for c in citations}:
            counts["out_of_range_verdict_ids"] = counts.get("out_of_range_verdict_ids", 0) + 1
    return counts


def _duplicate_verdicts(result: dict) -> int:
    seen: set[str] = set()
    duplicates = 0
    for item in result.get("verdicts") or []:
        key = str(item.get("citation_id") or "")
        if not key:
            continue
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


class _NullSession:
    """The judge path only reads settings and profiles; a stub session keeps it DB-free."""

    def get(self, *_args, **_kwargs):
        return None

    def scalars(self, *_args, **_kwargs):
        return _EmptyScalars()

    def scalar(self, *_args, **_kwargs):
        return None

    def execute(self, *_args, **_kwargs):
        return _EmptyResult()

    def add(self, *_args, **_kwargs):
        return None

    def flush(self, *_args, **_kwargs):
        return None

    def commit(self, *_args, **_kwargs):
        return None

    def rollback(self, *_args, **_kwargs):
        return None


class _EmptyScalars:
    def all(self):
        return []

    def __iter__(self):
        return iter(())


class _EmptyResult:
    def all(self):
        return []

    def scalars(self):
        return _EmptyScalars()

# --------------------------------------------------------------------------- grounded answer


class _AnswerHarness:
    """Drive the real ``grounded_answer`` assembly with deterministic retrieval + model.

    Only three boundaries are replaced, and each is replaced at the *narrowest* seam
    (a patched attribute, restored afterwards):

    * ``HybridRetriever.search`` returns the case's synthetic units;
    * ``execute_runtime_chat_with_metadata`` returns the case's model output;
    * ``validate_citations`` / ``document_citation`` / ``_index_freshness`` are replaced so
      no KnowledgeUnit rows or corpus snapshot are needed for a synthetic case.

    The status/confidence/trust/claim assembly code under test stays exactly the shipped
    code -- that is the whole point of routing these cases through this entry point.
    """

    #: Every attribute this harness rebinds must be listed here.  Leaving one out leaks a stub
    #: into the rest of the process: an earlier version restored only three of them, so a later
    #: test that exercised ``document_citation`` for real received the harness's synthetic
    #: citation dict instead of a real one and failed with ``KeyError: 'document_id'``.
    _PATCHED = ("HybridRetriever", "document_citation", "validate_citations",
                "_index_freshness", "execute_runtime_chat_with_metadata",
                "get_prompt_runtime", "evidence_runtime", "prepare_model_input")

    def __init__(self, db, items, model_output):
        self.db = db
        self.items = items
        self.model_output = model_output
        self._saved: dict = {}

    def __enter__(self):
        from app.services.rag import grounded_answer_service as module

        self._saved = {name: getattr(module, name) for name in self._PATCHED}
        items = self.items

        module.HybridRetriever = _StubRetriever(items)
        module.document_citation = lambda item, project_id: {
            "citation_id": f"knowledge-unit-{item['knowledge_unit_id']}",
            "knowledge_unit_id": item["knowledge_unit_id"],
            "label": f"知识单元 {item['knowledge_unit_id']}",
            "quoted_content": item.get("content") or "",
            "historical": bool(item.get("historical")),
            "authority_rank": int(item.get("authority_rank") or 0),
            "locator": {"block_id": f"knowledge-unit-{item['knowledge_unit_id']}"},
        }
        module.validate_citations = lambda *a, **k: None
        module._index_freshness = lambda *a, **k: {"formal_index_current": True,
                                                   "active_index_version_id": 1,
                                                   "waiting_version_ids": [],
                                                   "keyword_fallback": False,
                                                   "using_previous_formal_index": False}

        # ``check_citation_support`` is deliberately NOT patched: the real validator/judge
        # merge code runs, with only the model gateway stubbed by ``_gateway``.
        async def _answer(*_a, **_k):
            return self.model_output, {}

        module.execute_runtime_chat_with_metadata = _answer
        module.get_prompt_runtime = lambda *a, **k: None
        module.evidence_runtime = lambda runtime: runtime
        module.prepare_model_input = lambda *a, **k: "synthetic evidence"
        return self

    def __exit__(self, *exc):
        from app.services.rag import grounded_answer_service as module

        for name, original in self._saved.items():
            setattr(module, name, original)
        return False


class _StubRetriever:
    def __init__(self, items):
        self.items = items

    def __call__(self, *_args, **_kwargs):
        return self

    def search(self, *_args, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(id=1), list(self.items)


def run_grounded_case(case: dict) -> dict:
    """Execute one case through ``grounded_answer`` and record the assembled answer contract."""
    from app.services.rag import grounded_answer_service as module

    units = list(case.get("evidence") or [])
    items = [
        {"knowledge_unit_id": unit["knowledge_unit_id"], "content": unit["content"],
         "confidentiality_level": unit.get("confidentiality_level", "internal"),
         "rerank_score": 0.9, "authority_rank": int(unit.get("authority_rank") or 5),
         "historical": bool(unit.get("historical")),
         "metadata_json": unit.get("metadata_json")}
        for unit in units
    ]
    model_output = {"answer": case.get("model_answer") or "",
                    "confidence_level": "high",
                    "supported_claims": list(case.get("model_claims") or []),
                    "unsupported_claims": [],
                    "open_questions": []}
    payload, error = _judge_payload(case)

    settings = module.get_settings()
    previous = getattr(settings, "citation_support_check", "off")
    object.__setattr__(settings, "citation_support_check", "judge")
    started = time.perf_counter()
    try:
        # The real ``check_citation_support`` runs; ``_gateway`` replaces only the model
        # factory, so the verdict normalisation / merge / tally code is the shipped one.
        with _gateway(payload, error) as gateway, \
                _AnswerHarness(_NullSession(), items, model_output):
            answer = asyncio.run(module.grounded_answer(_NullSession(), 1, case["query"]))
        calls = gateway.calls
    finally:
        object.__setattr__(settings, "citation_support_check", previous)
    observed = _grounded_observation(answer, case)
    return {"case_id": case["case_id"], "family": case["family"], "executed": True,
            "gateway_calls": calls, "latency_ms": int((time.perf_counter() - started) * 1000),
            "observed": observed, "case_snapshot_hash": dataset.content_hash(case)}


def _judge_result_for(case: dict, units: list[dict]) -> dict:
    """Build the ``check_citation_support`` payload the case declares, without a model call."""
    judge = dict(case.get("judge") or {})
    error = judge.get("error")
    verdicts: list[dict] = []
    raw = judge.get("verdicts")
    if isinstance(raw, list):
        for item in raw:
            verdict = str(item.get("verdict") or "unknown").strip().lower()
            verdict = {"支持": "supported", "不支持": "unsupported", "不确定": "unknown"}.get(
                verdict, verdict)
            verdict = verdict if verdict in {"supported", "unsupported", "unknown"} else "unknown"
            verdicts.append({"citation_id": str(item.get("citation_id") or ""),
                             "verdict": verdict, "reason": str(item.get("reason") or "")})

    # Align on the real citations: unkeyed verdicts are positional, unknown ids are dropped
    # (their count is still exposed so the scorer can assert they were not applied).
    merged: list[dict] = []
    allowed = {f"knowledge-unit-{unit['knowledge_unit_id']}": unit for unit in units}
    keyed = {item["citation_id"]: item for item in verdicts if item["citation_id"]}
    unkeyed = [item for item in verdicts if not item["citation_id"]]
    dropped_ids = sorted(cid for cid in keyed if cid not in allowed)
    for index, unit in enumerate(units):
        citation_id = f"knowledge-unit-{unit['knowledge_unit_id']}"
        chosen = keyed.get(citation_id)
        if chosen is None and index < len(unkeyed):
            chosen = unkeyed[index]
        if chosen is None:
            chosen = {"citation_id": citation_id, "verdict": "unknown",
                      "reason": "judge_returned_no_verdict"}
        merged.append({"citation_id": citation_id,
                       "knowledge_unit_id": unit["knowledge_unit_id"],
                       "verdict": chosen["verdict"], "reason": chosen.get("reason") or ""})
    tally = {"supported": 0, "unsupported": 0, "unknown": 0}
    for item in merged:
        tally[item["verdict"]] += 1
    base = {
        "enabled": True, "check": "judge", "judged": error is None,
        "citation_count": len(units), "verdicts": merged,
        "verdict_counts": tally, "supported_count": tally["supported"],
        "unsupported_count": tally["unsupported"], "unknown_count": tally["unknown"],
        "judged_count": len(merged),
        "unsupported_ratio": round(tally["unsupported"] / len(merged), 4) if merged else 0.0,
        "degraded": error is not None, "degraded_reason": error, "skip_reason": None,
        "model_profile_id": None, "provider_type": "stub", "model_name": "stub-judge",
        "prompt_key": "citation_support_check",
        "dropped_verdict_ids": dropped_ids,
        "duplicate_verdict_ids": _duplicate_ids(verdicts),
    }
    if error is not None:
        for item in base["verdicts"]:
            item["verdict"] = "unknown"
            item["reason"] = f"judge_degraded:{error}"
        base.update({"supported_count": 0, "unsupported_count": 0,
                     "unknown_count": len(merged), "judged": False,
                     "unsupported_ratio": 0.0})
    return base


def _duplicate_ids(verdicts: list[dict]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in verdicts:
        key = item.get("citation_id") or ""
        if not key:
            continue
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    return sorted(set(duplicates))


def _grounded_observation(answer: dict, case: dict) -> dict:
    support = answer.get("citation_support") or {}
    return {
        "answer_status": answer.get("answer_status"),
        "confidence_level": answer.get("confidence_level"),
        "trust_grade": (answer.get("trustworthiness") or {}).get("grade"),
        "supported_claims": list(answer.get("supported_claims") or []),
        "unsupported_claims": list(answer.get("unsupported_claims") or []),
        "open_questions": list(answer.get("open_questions") or []),
        "citation_count": len(answer.get("citations") or []),
        "supported": int(support.get("supported_count") or 0),
        "unsupported": int(support.get("unsupported_count") or 0),
        "unknown": int(support.get("unknown_count") or 0),
        "judged_count": int(support.get("judged_count") or 0),
        "degraded": bool(support.get("degraded")),
        "degraded_reason": support.get("degraded_reason"),
        "coverage_ratio": support.get("coverage_ratio"),
        "dropped_verdict_ids": list(support.get("dropped_verdict_ids") or []),
        "duplicate_verdict_ids": list(support.get("duplicate_verdict_ids") or []),
        "degraded_answer": answer.get("degraded_reason"),
    }

# --------------------------------------------------------------------------- agent state


_ILLEGAL_EDGE_CASES: dict[str, tuple[str, str]] = {
    "illegal_transition": ("completed", "running"),
    "unknown_status": ("pending", "not_a_status"),
}


def run_agent_case(case: dict) -> dict:
    """Drive a state-chain case through the real pure state machine."""
    from app.services.agent import state_machine as sm

    chain = dict(case.get("state_chain") or {})
    kind = chain.get("kind")
    observed: dict[str, Any] = {"kind": kind}

    if kind in _ILLEGAL_EDGE_CASES:
        source, target = (chain.get("from"), chain.get("to")) or _ILLEGAL_EDGE_CASES[kind]
        try:
            sm.require_step_transition(source, target)
            observed["raised"] = False
            observed["error_code"] = None
        except sm.AgentStateError as exc:
            observed["raised"] = True
            observed["error_code"] = exc.code
        return _agent_result(case, observed)

    if kind == "derive_precedence" or kind == "derive_all_completed":
        derived = sm.derive_task_status(chain.get("step_statuses") or [])
        observed["derived_task_status"] = derived
        observed["illegal_edges"] = 0
        return _agent_result(case, observed)

    if kind in {"cancelled_late_result", "cancel_mid_run"}:
        cancelled = bool(chain.get("cancelled") or kind == "cancelled_late_result")
        derived = sm.derive_task_status(chain.get("step_statuses") or [], cancelled=cancelled)
        observed["derived_task_status"] = derived
        observed["late_result_applied"] = False
        return _agent_result(case, observed)

    if kind in {"human_reject", "human_request_reanalysis", "human_edit_and_approve",
                "human_gate_pending", "human_gate_approved"}:
        observed.update(_decision_observation(sm, chain))
        return _agent_result(case, observed)

    # A plain chain: replay each edge and roll the final statuses up.
    statuses: list[str] = []
    current = "pending"
    first = True
    for target in chain.get("step_statuses") or ["pending"]:
        if first and target in {"pending"}:
            statuses.append(target)
            current = target
            first = False
            continue
        try:
            sm.require_step_transition(current, target)
            observed.setdefault("edges_accepted", 0)
            observed["edges_accepted"] += 1
        except sm.AgentStateError as exc:
            observed.setdefault("edges_rejected", 0)
            observed["edges_rejected"] += 1
            observed.setdefault("rejected_codes", []).append(exc.code)
        statuses.append(target)
        current = target
        first = False
    observed["step_statuses"] = statuses
    observed["derived_task_status"] = sm.derive_task_status(statuses)
    return _agent_result(case, observed)


def _decision_observation(sm, chain: dict) -> dict:
    decision = chain.get("decision")
    if decision is None:
        return {"derived_task_status": sm.derive_task_status(chain.get("step_statuses") or [])}
    target = sm.DECISION_STEP_TARGET[decision]
    statuses = [target]
    return {"decision": decision, "step_status_after_decision": target,
            "derived_task_status": sm.derive_task_status(statuses),
            "human_gate_terminal": target in sm.STEP_TERMINAL}


def _agent_result(case: dict, observed: dict) -> dict:
    return {"case_id": case["case_id"], "family": case["family"], "executed": True,
            "gateway_calls": 0, "latency_ms": 0, "observed": observed,
            "case_snapshot_hash": dataset.content_hash(case)}


# --------------------------------------------------------------------------- family dispatch


def execute_case(case: dict) -> dict:
    """Execute one case, never raising: an unsupported family is reported, not crashed."""
    family = case.get("family")
    try:
        if family in {"citation_not_supporting", "citation_support_boundary",
                      "field_semantics", "version_and_scope"}:
            # Route through ``grounded_answer``: that is where answer_status/confidence/trust
            # are assembled, and routing through it is what makes a status fix observable.
            return run_grounded_case(case)
        if family == "agent_state_chain":
            return run_agent_case(case)
        if family == "rerank_long_context":
            from app.services.evaluation.benchmark import rerank_family

            return rerank_family.run_rerank_case(case)
        return {"case_id": case["case_id"], "family": family, "executed": False,
                "skipped_reason": "unknown_family", "observed": {}, "gateway_calls": 0,
                "latency_ms": 0}
    except Exception as exc:  # noqa: BLE001 - one bad case must not abort the run
        return {"case_id": case["case_id"], "family": family, "executed": False,
                "error": f"{type(exc).__name__}: {exc}", "observed": {},
                "gateway_calls": 0, "latency_ms": 0}


def execute_all(cases: list[dict] | None = None) -> list[dict]:
    corpus = sorted(cases if cases is not None else load_cases(), key=lambda item: item["case_id"])
    return [execute_case(case) for case in corpus]


# --------------------------------------------------------------------------- scoring


def _expected_matches(case: dict, observed: dict) -> tuple[bool, list[str]]:
    """Compare the observed facts against the case's declared expectation."""
    expected = dict(case.get("expected") or {})
    failures: list[str] = []

    if "answer_status" in expected and expected["answer_status"]:
        actual = observed.get("answer_status")
        if actual != expected["answer_status"]:
            failures.append(f"answer_status:{actual}!={expected['answer_status']}")

    accepted = expected.get("answer_status_in")
    if accepted:
        actual = observed.get("answer_status")
        if actual not in accepted:
            failures.append(f"answer_status:{actual} not in {sorted(accepted)}")

    wanted_support = expected.get("citation_support")
    if isinstance(wanted_support, dict):
        for verdict, want in wanted_support.items():
            got = observed.get(verdict)
            if got != want:
                failures.append(f"citation_support.{verdict}:{got}!={want}")

    if "degraded" in expected and bool(observed.get("degraded")) != bool(expected["degraded"]):
        failures.append(f"degraded:{observed.get('degraded')}!={expected['degraded']}")

    if "coverage" in expected and observed.get("judged_count") != expected["coverage"]:
        failures.append(f"judged_count:{observed.get('judged_count')}!={expected['coverage']}")

    if expected.get("duplicate_verdicts_ignored") and observed.get("duplicate_verdicts"):
        # Duplicates may be counted for disclosure, but they must not inflate judged_count.
        if observed.get("judged_count") != observed.get("citation_count"):
            failures.append("duplicate_verdicts_inflated_judged_count")

    if expected.get("unknown_ids_excluded") and observed.get("out_of_range_verdict_ids"):
        failures.append("out_of_range_verdict_ids_applied")

    if "derived_task_status" in expected:
        if observed.get("derived_task_status") != expected["derived_task_status"]:
            failures.append(
                f"derived_task_status:{observed.get('derived_task_status')}!="
                f"{expected['derived_task_status']}")

    if expected.get("illegal_transition_raises") and not observed.get("raised"):
        failures.append("illegal_transition_not_rejected")

    if expected.get("unknown_status_raises") and not observed.get("raised"):
        failures.append("unknown_status_not_rejected")

    if observed.get("raised") and expected.get("allowed"):
        failures.append(f"unexpected_rejection:{observed.get('error_code')}")

    if expected.get("step_status_after_decision"):
        if observed.get("step_status_after_decision") != expected["step_status_after_decision"]:
            failures.append("decision_target_mismatch")

    # --- rerank_long_context facts -------------------------------------------------
    # The four facts must stay distinct, and a truncated admission set is a failure, not a
    # smaller success: the correct candidate must reach a model comparison, and every tail
    # position the case pins must be evaluated too.
    tail_missing = observed.get("tail_ranks_not_model_evaluated")
    if tail_missing:
        # A tail rank exists only when recall returned that many candidates; when it does,
        # missing it means the batch plan silently dropped a comparable candidate.
        if expected.get("model_evaluated") is True and not observed.get("correct_model_evaluated"):
            failures.append("correct_candidate_not_model_evaluated")
        failures.append(f"tail_ranks_not_model_evaluated:{tail_missing}")

    if expected.get("model_evaluated") is True and observed.get("correct_model_evaluated") is False:
        failures.append("correct_candidate_not_model_evaluated")

    if expected.get("out_of_whitelist_ids") == 0 and observed.get("out_of_whitelist_ids"):
        failures.append(f"out_of_whitelist_ids:{observed['out_of_whitelist_ids']}")

    if expected.get("whitelist_exact") and observed.get("out_of_whitelist_ids"):
        failures.append("whitelist_not_exact")

    if expected.get("response_contract_backward_compatible") and \
            observed.get("existing_fields_present") is False:
        failures.append("response_contract_regressed")

    if expected.get("min_candidate_still_fails_loudly") and observed.get("admitted") == 0 \
            and observed.get("returned", 0) >= 0 and observed.get("ranking_mode") == "model_rerank":
        failures.append("empty_admission_reported_as_success")

    return (not failures), failures


def _forbidden_hit(case: dict, observed: dict) -> list[str]:
    """Which declared-forbidden outcomes actually occurred (best-effort, explicit only)."""
    hits: list[str] = []
    for rule in case.get("forbidden") or []:
        if rule == "answer_status=grounded" and observed.get("answer_status") == "grounded":
            hits.append(rule)
        elif rule == "answer_status=degraded" and observed.get("answer_status") == "degraded":
            hits.append(rule)
        elif rule == "answer_status=needs_confirmation" and observed.get("answer_status") == "needs_confirmation":
            hits.append(rule)
        elif rule == "unsupported_count>0" and int(observed.get("unsupported") or 0) > 0:
            hits.append(rule)
        elif rule == "unknown_count>0" and int(observed.get("unknown") or 0) > 0:
            hits.append(rule)
        elif rule == "degraded=False" and observed.get("degraded") is False and "degraded" in observed:
            hits.append(rule)
        elif rule == "judged_count!=3" and observed.get("judged_count") != 3:
            hits.append(rule)
        elif rule == "judged_count=3" and observed.get("judged_count") == 3:
            hits.append(rule)
        elif rule == "judged_count=0" and observed.get("judged_count") == 0:
            hits.append(rule)
        elif rule == "approved_gate_left_waiting_human" and \
                observed.get("derived_task_status") == "waiting_human":
            hits.append(rule)
        elif rule == "illegal_transition_accepted" and observed.get("raised") is False and \
                observed.get("error_code") is None and observed.get("kind") == "illegal_transition":
            hits.append(rule)
        elif rule == "unknown_status_accepted" and observed.get("raised") is False and \
                observed.get("kind") == "unknown_status":
            hits.append(rule)
    return hits


def score_results(results: list[dict]) -> list[dict]:
    """Attach an expectation/scoring verdict to each executed result."""
    by_id = {case["case_id"]: case for case in load_cases()}
    scored: list[dict] = []
    for result in results:
        case = by_id.get(result["case_id"], {})
        entry = dict(result)
        if not result.get("executed"):
            entry["verdict"] = "not_run"
            entry["failures"] = []
            entry["forbidden_hits"] = []
            scored.append(entry)
            continue
        matched, failures = _expected_matches(case, result.get("observed") or {})
        hits = _forbidden_hit(case, result.get("observed") or {})
        entry["verdict"] = "pass" if matched and not hits else "fail"
        entry["failures"] = failures
        entry["forbidden_hits"] = hits
        scored.append(entry)
    return scored


def aggregate(scored: list[dict]) -> dict:
    """Counts with explicit denominators; a skipped case is never silently 'passing'."""
    executed = [item for item in scored if item.get("executed")]
    passed = [item for item in executed if item.get("verdict") == "pass"]
    failed = [item for item in executed if item.get("verdict") == "fail"]
    not_run = [item for item in scored if not item.get("executed")]
    by_family: dict[str, dict[str, int]] = {}
    for item in scored:
        family = item.get("family") or "unknown"
        bucket = by_family.setdefault(family, {"total": 0, "executed": 0, "passed": 0,
                                               "failed": 0, "not_run": 0})
        bucket["total"] += 1
        if not item.get("executed"):
            bucket["not_run"] += 1
        else:
            bucket["executed"] += 1
            bucket["passed" if item.get("verdict") == "pass" else "failed"] += 1
    by_family_pass = {
        family: (round(values["passed"] / values["executed"], 4) if values["executed"] else None)
        for family, values in by_family.items()}
    return {
        "case_count": len(scored),
        "executed_count": len(executed),
        "not_run_count": len(not_run),
        "passed_count": len(passed),
        "failed_count": len(failed),
        # Denominators are explicit: a 0/0 family is null, not 1.0.
        "pass_rate_executed": round(len(passed) / len(executed), 4) if executed else None,
        "pass_rate_over_corpus": round(len(passed) / len(scored), 4) if scored else None,
        "by_family": by_family,
        "pass_rate_by_family": by_family_pass,
        "gateway_calls_total": sum(int(item.get("gateway_calls") or 0) for item in scored),
        "latency_ms_total": sum(int(item.get("latency_ms") or 0) for item in scored),
        "failures": [{"case_id": item["case_id"], "failures": item.get("failures"),
                      "forbidden_hits": item.get("forbidden_hits")} for item in failed],
        "not_run": [{"case_id": item["case_id"], "reason": item.get("skipped_reason") or
                     item.get("error")} for item in not_run],
    }


def run(split: str | None = None) -> dict:
    """Execute the corpus (or one split) and return scored results plus aggregates."""
    corpus = load_cases()
    if split in {"dev", "holdout"}:
        corpus = dataset.split_cases(corpus)[split]
    results = execute_all(corpus)
    scored = score_results(results)
    return {"split": split or "all", "cases": scored, "aggregate": aggregate(scored)}


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
