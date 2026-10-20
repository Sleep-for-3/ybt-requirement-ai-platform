"""Real-model acceptance for the two overnight work packages (B citation, C rerank).

Different question from the Mock benchmark: the benchmark proves the *protocol* is right; this
proves the shipped **real** provider path works end to end and measures what it actually costs.

What is real here
-----------------
* real provider (``LLM_BASE_URL`` / ``LLM_MODEL`` from ``backend/.env``, profile ``公司网关
  DeepSeek-V4-Flash（真实模型）``), real HTTP, real latency and real ``usage`` when returned;
* real PostgreSQL database, real ``KnowledgeUnit`` rows, real ``HybridRetriever``;
* real ``grounded_answer`` assembly with ``citation_support_check="judge"`` so the judge is a
  real model call, not a stub.

What is bounded
---------------
An explicit call cap, a wall-clock cap and a token cap are enforced *here*, not assumed: the
run stops when any budget is exhausted and reports how much of the case list it covered.  A
provider that omits ``usage`` is recorded as ``unknown``, never as 0.

Usage
-----
    <venv python> scripts/real_model_acceptance.py [--cases-citation N] [--cases-rerank N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

#: Hard budgets. Exceeding any one stops the run; the report says exactly what was covered.
MAX_MODEL_CALLS = 24
MAX_WALL_SECONDS = 900
MAX_TOTAL_TOKENS = 220_000

#: The only project the outbound whitelist authorizes AND that carries real knowledge.
PROJECT_ID = 1


@dataclass
class Budget:
    """A hard, measured budget. Nothing here is inferred from configuration."""

    max_calls: int = MAX_MODEL_CALLS
    max_seconds: float = MAX_WALL_SECONDS
    max_tokens: int = MAX_TOTAL_TOKENS
    calls: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.perf_counter)
    usages: list[dict] = field(default_factory=list)
    stopped_reason: str | None = None

    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def charge(self, metadata) -> None:
        self.calls += 1
        usage = None
        if metadata is not None:
            usage = getattr(metadata, "token_usage", None)
        total = None
        if isinstance(usage, dict):
            raw = usage.get("total_tokens")
            if isinstance(raw, int):
                total = raw
                self.tokens += raw
        self.usages.append({
            "call": self.calls,
            "latency_ms": getattr(metadata, "latency_ms", None) if metadata else None,
            "total_tokens": total if total is not None else "unknown",
            "usage_available": bool(isinstance(usage, dict) and usage.get("usage_available")),
            "model": getattr(metadata, "model", None) if metadata else None,
            "provider": getattr(metadata, "provider", None) if metadata else None,
            "http_status": getattr(metadata, "http_status", None) if metadata else None,
            "retry_count": getattr(metadata, "retry_count", None) if metadata else None,
        })

    def exhausted(self) -> str | None:
        if self.calls >= self.max_calls:
            return f"call_cap({self.max_calls})"
        if self.elapsed() >= self.max_seconds:
            return f"wall_clock_cap({self.max_seconds:.0f}s)"
        if self.tokens >= self.max_tokens:
            return f"token_cap({self.max_tokens})"
        return None

    def summary(self) -> dict:
        latencies = [item["latency_ms"] for item in self.usages
                     if isinstance(item.get("latency_ms"), int)]
        unknown = sum(1 for item in self.usages if item["total_tokens"] == "unknown")
        return {
            "max_calls": self.max_calls,
            "max_wall_seconds": self.max_seconds,
            "max_total_tokens": self.max_tokens,
            "calls_made": self.calls,
            "total_tokens": self.tokens if unknown == 0 else "at_least_" + str(self.tokens),
            "calls_without_usage": unknown,
            "wall_seconds": round(self.elapsed(), 1),
            "latency_ms": {
                "min": min(latencies) if latencies else None,
                "p50": round(statistics.median(latencies)) if latencies else None,
                "max": max(latencies) if latencies else None,
            },
            "stopped_reason": self.stopped_reason,
            "per_call": self.usages,
        }


class _ChargingService:
    """Observes the real provider client without altering it."""

    def __init__(self, inner, budget: Budget):
        self._inner = inner
        self._budget = budget

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def chat_json(self, system_prompt, user_prompt):
        result = await self._inner.chat_json(system_prompt, user_prompt)
        self._budget.charge(getattr(self._inner, "last_call", None))
        return result

    async def embed_texts(self, texts):
        return await self._inner.embed_texts(texts)


def _patch_charge(budget: Budget):
    """Route every gateway construction through the charging wrapper; return the undo.

    Two seams must be patched, not one: the RAG path looks the factory up on
    ``prompt_runtime`` at call time, while ``ai_skills.runtime`` bound the name at import
    time.  Patching only the first left real rerank calls uncounted (``calls_made=0`` despite
    three real model calls), which would have made the token budget a fiction.
    """
    from app.services.ai_skills import runtime as skill_runtime
    from app.services.llm import prompt_runtime

    original = prompt_runtime.get_runtime_llm_service
    original_skill = skill_runtime.get_runtime_llm_service

    def factory(*args, **kwargs):
        return _ChargingService(original(*args, **kwargs), budget)

    def skill_factory(*args, **kwargs):
        return _ChargingService(original_skill(*args, **kwargs), budget)

    prompt_runtime.get_runtime_llm_service = factory
    skill_runtime.get_runtime_llm_service = skill_factory

    def undo():
        prompt_runtime.get_runtime_llm_service = original
        skill_runtime.get_runtime_llm_service = original_skill

    return undo, []


def audit_calls_since(moment) -> dict:
    """Read the product's own audit trail for calls made during this run.

    The in-process wrapper cannot see every path: ``ai_skills.runtime`` imported the factory name
    at module import time, so a real rerank call bypassed it (``calls_made=0`` while three real
    model calls demonstrably happened).  ``ModelCallLog`` is the authoritative record the product
    itself writes, so the budget is reconciled against it instead of against my own counter.
    """
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import ModelCallLog

    with SessionLocal() as db:
        rows = db.scalars(select(ModelCallLog).where(
            ModelCallLog.created_at >= moment).order_by(ModelCallLog.id)).all()
        entries = []
        tokens = 0
        unknown = 0
        for row in rows:
            usage = row.token_usage_json or {}
            total = usage.get("total_tokens")
            if isinstance(total, int):
                tokens += total
            else:
                unknown += 1
            entries.append({
                "id": row.id,
                "skill_key": row.skill_key,
                "prompt_key": row.prompt_key,
                "model": row.model_name,
                "provider": row.provider,
                "status": row.status,
                "execution_kind": row.execution_kind,
                "latency_ms": row.latency_ms,
                "total_tokens": total if isinstance(total, int) else "unknown",
                "usage_available": bool(usage.get("usage_available")),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
    return {"source": "ModelCallLog", "calls": len(entries),
            "total_tokens": tokens if unknown == 0 else f"at_least_{tokens}",
            "calls_without_usage": unknown, "entries": entries}


# --------------------------------------------------------------------------- B: citation


def run_citation_cases(limit: int) -> dict:
    """Real retrieval + real answer + real judge over real bank knowledge."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.settings import get_settings
    from app.models import KnowledgeUnit, Project
    from app.services.rag import grounded_answer_service as module

    budget = Budget()
    _run_started = datetime.now(UTC)
    # Realistic questions about real regulation knowledge; each is answered from the real
    # knowledge base, so retrieval and citation support are exercised for real.
    queries = [
        "一表通报送中客户证件类型的填报要求是什么？",
        "大额风险暴露的统计口径如何界定？",
        "理财产品销售需要执行哪些适当性要求？",
        "贷款五级分类的判断标准是什么？",
        "同业业务的风险加权资产如何计量？",
        "表外业务在监管报表中如何列报？",
        "客户风险等级评估的有效期是多久？",
        "流动性覆盖率的最低监管要求是多少？",
    ][:limit]

    results = []
    undo, _ = _patch_charge(budget)
    settings = get_settings()
    previous_check = getattr(settings, "citation_support_check", "off")
    try:
        object.__setattr__(settings, "citation_support_check", "judge")
        with SessionLocal() as db:
            project = db.get(Project, PROJECT_ID)
            if project is None:
                return {"error": f"project {PROJECT_ID} not found"}
            for query in queries:
                reason = budget.exhausted()
                if reason:
                    budget.stopped_reason = reason
                    break
                started = time.perf_counter()
                entry: dict = {"query": query}
                try:
                    answer = asyncio.run(module.grounded_answer(
                        db, PROJECT_ID, query, interactive=False,
                        model_profile_id=4, top_k=5, retrieval_mode="keyword_only"))
                    support = answer.get("citation_support") or {}
                    entry.update({
                        "executed": True,
                        "answer_status": answer.get("answer_status"),
                        "confidence_level": answer.get("confidence_level"),
                        "trust_grade": (answer.get("trustworthiness") or {}).get("grade"),
                        "citation_count": len(answer.get("citations") or []),
                        "answer_chars": len(str(answer.get("answer") or "")),
                        "verification": support.get("verification"),
                        "claims_total": support.get("claims_total"),
                        "claims_judged": support.get("claims_judged"),
                        "claims_unsupported": support.get("claims_unsupported"),
                        "claims_unknown": support.get("claims_unknown"),
                        "claim_coverage": support.get("claim_coverage"),
                        "claim_coverage_dimension": support.get("claim_coverage_dimension"),
                        "claim_coverage_numerator": support.get("claim_coverage_numerator"),
                        "claim_coverage_denominator": support.get("claim_coverage_denominator"),
                        "citation_coverage": support.get("citation_coverage"),
                        "claims_unjudged": support.get("claims_unjudged"),
                        "claim_judgement": support.get("claim_judgement"),
                        "coverage_truncated": support.get("coverage_truncated"),
                        "citation_supported": support.get("supported_count"),
                        "citation_unsupported": support.get("unsupported_count"),
                        "citation_unknown": support.get("unknown_count"),
                        "degraded": support.get("degraded"),
                        "degraded_reason": support.get("degraded_reason"),
                        "judged_by_real_model": bool(support.get("model_name")),
                        "judge_model": support.get("model_name"),
                        "unverified_claims": list(answer.get("unverified_claims") or [])[:3],
                        "open_questions": list(answer.get("open_questions") or [])[:2],
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    })
                except Exception as exc:  # noqa: BLE001 - a provider failure is a result
                    entry.update({"executed": False,
                                  "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
                results.append(entry)
    finally:
        object.__setattr__(settings, "citation_support_check", previous_check)
        undo()

    executed = [item for item in results if item.get("executed")]
    return {
        "family": "B_real_citation_support",
        "project_id": PROJECT_ID,
        "requested": len(queries),
        "executed": len(executed),
        "not_run": len(results) - len(executed),
        "budget": budget.summary(),
        "audit": audit_calls_since(_run_started),
        "observed": {
            "answered": len(executed),
            "degraded": sum(1 for item in executed if item.get("degraded")),
            "needs_confirmation": sum(1 for item in executed
                                      if item.get("answer_status") == "needs_confirmation"),
            "grounded": sum(1 for item in executed
                            if item.get("answer_status") == "grounded"),
            "with_citations": sum(1 for item in executed if (item.get("citation_count") or 0) > 0),
            "judge_used_real_model": sum(1 for item in executed
                                         if item.get("judged_by_real_model")),
            "verifications": sorted({str(item.get("verification")) for item in executed}),
        },
        "cases": results,
    }


# --------------------------------------------------------------------------- C: rerank


def run_rerank_cases(limit: int) -> dict:
    """Real recall over real catalog columns + REAL model rerank.

    This is the only place the shipped rerank prompt reaches a real provider, so it also
    measures whether the batched plan is affordable at production latency.
    """
    from app.core.database import SessionLocal
    from app.models import CatalogColumn, Project, TargetField
    from app.schemas.ai_skill_ranking import FieldCandidateQuery, FieldRerankRequest
    from app.services.ai_skills import field_candidates, field_rerank
    from app.services.auth.dependencies import Principal
    from sqlalchemy import select, func

    budget = Budget()
    _run_started = datetime.now(UTC)
    results = []
    undo, _ = _patch_charge(budget)
    try:
        with SessionLocal() as db:
            from app.models import User
            user = db.scalar(select(User).where(User.status == "active").order_by(User.id))
            if user is None:
                return {"error": "no active user for a principal"}
            principal = Principal(user.id, user.username, user.username)

            targets = db.scalars(
                select(TargetField).where(TargetField.project_id == PROJECT_ID).limit(limit)).all()
            if not targets:
                return {"error": "no target fields in the authorized project",
                        "catalog_columns": db.scalar(select(func.count()).select_from(
                            CatalogColumn).where(CatalogColumn.project_id == PROJECT_ID))}

            for target in targets:
                reason = budget.exhausted()
                if reason:
                    budget.stopped_reason = reason
                    break
                entry: dict = {"target_field_id": target.id,
                               "field_code": target.field_code,
                               "field_name": target.field_name}
                started = time.perf_counter()
                try:
                    query = FieldCandidateQuery(
                        project_id=PROJECT_ID, target_field_id=target.id, top_k=15,
                        query=f"{target.field_name} {target.field_code}")
                    recall = field_candidates.recall_fields(db, principal, query)
                    request = FieldRerankRequest(input=query,
                                                 context_hash=recall["context_hash"])
                    response = asyncio.run(field_rerank.rerank_fields(db, principal, request))
                    # The service deliberately does not commit: ``api/ai_skills.py`` owns the
                    # transaction boundary.  Calling the service directly therefore has to
                    # reproduce it, otherwise the ModelCallLog rows (and any staged object) are
                    # rolled back and the audit trail silently loses the call.
                    db.commit()
                    meta = response.get("rerank") or {}
                    coverage = meta.get("coverage") or {}
                    entry.update({
                        "executed": True,
                        "recalled": recall["returned_count"],
                        "admitted": coverage.get("admitted"),
                        "model_evaluated": coverage.get("model_evaluated"),
                        "returned": len(response.get("candidates") or []),
                        "coverage_label": coverage.get("coverage"),
                        "unranked_count": len(coverage.get("unranked_ids") or []),
                        "ranking_mode": response.get("ranking_mode"),
                        "rerank_status": meta.get("status"),
                        "error_code": meta.get("error_code"),
                        "model_name": (meta.get("model_metadata") or {}).get("model_name"),
                        "rank_sources": sorted({
                            str(item.get("rank_source")) for item in response.get("candidates") or []}),
                        "execution_kind": (response.get("execution_metadata") or {}).get(
                            "execution_kind"),
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    })
                except Exception as exc:  # noqa: BLE001
                    entry.update({"executed": False,
                                  "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
                results.append(entry)
    finally:
        undo()

    executed = [item for item in results if item.get("executed")]
    applied = [item for item in executed if item.get("ranking_mode") == "model_rerank"]
    return {
        "family": "C_real_rerank",
        "project_id": PROJECT_ID,
        "requested": len(results),
        "executed": len(executed),
        "not_run": len(results) - len(executed),
        "budget": budget.summary(),
        "audit": audit_calls_since(_run_started),
        "observed": {
            "model_rerank_applied": len(applied),
            "fallback_only": len(executed) - len(applied),
            "full_coverage": sum(1 for item in executed
                                 if item.get("coverage_label") == "full"),
            "partial_coverage": sum(1 for item in executed
                                    if item.get("coverage_label") == "partial"),
            "real_model_names": sorted({str(item.get("model_name")) for item in executed}),
            "errors": [item["error"] for item in results if item.get("error")][:5],
        },
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-citation", type=int, default=8)
    parser.add_argument("--cases-rerank", type=int, default=6)
    parser.add_argument("--out", default="")
    parser.add_argument("--skip-citation", action="store_true")
    parser.add_argument("--skip-rerank", action="store_true")
    args = parser.parse_args(argv)

    payload: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "provider": {
            "base_url_env": "LLM_BASE_URL",
            "model_env": "LLM_MODEL",
            "profile_id": 4,
            "profile_note": "公司网关 DeepSeek-V4-Flash（真实模型）",
        },
        "budgets": {"max_calls": MAX_MODEL_CALLS, "max_wall_seconds": MAX_WALL_SECONDS,
                    "max_total_tokens": MAX_TOTAL_TOKENS},
    }
    if not args.skip_citation:
        payload["citation"] = run_citation_cases(args.cases_citation)
    if not args.skip_rerank:
        payload["rerank"] = run_rerank_cases(args.cases_rerank)

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
