"""⑧: opt-in LLM-judge faithfulness in the RAG evaluation run.

These tests drive the **real** ``rag_evaluator.run_evaluation`` and the real judge engine,
replacing only (a) the answer boundary ``rag_evaluator.grounded_answer`` and (b) the LLM gateway
factory ``app.services.llm.prompt_runtime.get_runtime_llm_service``. No network call is made.

Covered:
* ``ragas_judge_enabled=False`` (default): the summary key set, the notes, and every per-case
  execution metadata stay exactly what they were before this feature (frozen-set regression);
* ``True`` with a fixed judgement: ``faithfulness`` / ``faithfulness_denominator`` /
  ``unsupported_citation_ratio`` are correct and per-case metadata carries the verdicts;
* an unavailable gateway: the run still completes, faithfulness is reported as unjudged
  (denominator 0) and the retrieval metrics are untouched;
* empty-answer boundaries make no model call.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.settings import get_settings
from app.models import (
    ModelProfile,
    Project,
    RagEvaluationCase,
    RagEvaluationResult,
    RagEvaluationRun,
    RetrievalLog,
)
from app.services.evaluation import rag_evaluator
from app.services.llm.base import LLMProviderError, ModelCallMetadata
from app.services.rag.citation_support import judge_faithfulness

# The pre-feature summary contract. A judge-disabled run must produce exactly these keys.
FROZEN_SUMMARY_KEYS = frozenset(
    {
        "case_count",
        "successful_query_count",
        "retrieval_only_query_count",
        "degraded_query_count",
        "failed_query_count",
        "answer_coverage_denominator",
        "generation_coverage",
        "status_counts",
        "actual_chat_model",
        "actual_chat_profile_id",
        "metric_notes",
        "recall_at_5",
        "recall_at_10",
        "mrr",
        "source_hit_rate",
        "table_hit_rate",
        "field_hit_rate",
        "citation_coverage",
        "groundedness",
        "answer_correctness",
        "answer_correctness_denominator",
        "keyword_coverage",
        "evidence_keyword_coverage",
        "retrieval_latency_p50_ms",
        "retrieval_latency_p95_ms",
        "answer_latency_ms",
        "average_latency_ms",
        "indexing_throughput_chunks_per_second",
        "token_usage_total",
    }
)

FROZEN_METRIC_NOTE_KEYS = frozenset(
    {
        "retrieval_metrics",
        "groundedness",
        "answer_correctness",
        "keyword_coverage",
        "evidence_keyword_coverage",
        "not_expert_accuracy",
    }
)

JUDGE_SUMMARY_KEYS = frozenset({"faithfulness", "faithfulness_denominator", "unsupported_citation_ratio"})

CALL_COUNT = {"value": 0}


class _VerdictService:
    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    def __init__(self, payload):
        self.payload = payload

    async def chat_json(self, system_prompt, user_prompt):
        CALL_COUNT["value"] += 1
        return self.payload

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


class _FailingService:
    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    async def chat_json(self, system_prompt, user_prompt):
        CALL_COUNT["value"] += 1
        raise LLMProviderError("judge unavailable", error_type="timeout", detail="ReadTimeout")

    async def embed_texts(self, texts):
        raise LLMProviderError("judge unavailable", error_type="timeout")


def _install_gateway(monkeypatch, service_factory):
    def factory(*_args, **_kwargs):
        return service_factory()

    monkeypatch.setattr("app.services.llm.prompt_runtime.get_runtime_llm_service", factory)


@pytest.fixture()
def env(tmp_path):
    url = "sqlite:///" + (tmp_path / "faithfulness.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=None)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _judge_off(monkeypatch):
    CALL_COUNT["value"] = 0
    monkeypatch.setattr(get_settings(), "ragas_judge_enabled", False, raising=False)
    yield


def _profiles(db, *, count=1):
    profiles = []
    for index in range(1, count + 1):
        profile = ModelProfile(
            profile_name=f"profile-{index}", provider_type="mock",
            model_name=f"model-{chr(64 + index)}", enabled=True, local_only=True,
            supports_structured_output=True, max_context_tokens=8192, temperature=0.0,
            config_json={}, created_by="c08",
        )
        db.add(profile)
        profiles.append(profile)
    db.commit()
    for profile in profiles:
        db.refresh(profile)
    return profiles


def _case(project_id, index, **overrides):
    values = {
        "project_id": project_id,
        "case_name": f"case-{index}",
        "case_type": "retrieval",
        "query_text": f"问题-{index}",
        "expected_knowledge_unit_ids_json": [index],
        "expected_answer_keywords_json": ["余额"],
        "enabled": True,
    }
    values.update(overrides)
    return RagEvaluationCase(**values)


def _seed_run(db, *, cases, profile_id=None, mode="hybrid"):
    project = Project(name="C08 忠实性评测项目")
    db.add(project)
    db.flush()
    rows = [_case(project.id, index) for index in cases]
    run = RagEvaluationRun(
        project_id=project.id, run_name="c08", model_profile_id=profile_id,
        retrieval_config_json={"retrieval_mode": mode, "top_k": 10},
        status="pending", started_at=datetime.now(UTC), created_by="c08",
    )
    db.add_all([*rows, run])
    db.commit()
    db.refresh(run)
    return project.id, run


def _install_fake_answer(monkeypatch, *, status, answer, claims=None, citations=None,
                         reason=None):
    """Replace only the answer boundary; the evaluator and the judge engine stay real."""

    captured: dict[str, object] = {}

    async def fake_grounded_answer(db, project_id, query, **kwargs):
        captured.setdefault("calls", []).append(kwargs)
        unit_id = int(query.rsplit("-", 1)[1])
        log = RetrievalLog(
            project_id=project_id, query_text=query, query_type=kwargs["retrieval_mode"],
            filters_json={}, retrieval_strategy=kwargs["retrieval_mode"],
            keyword_result_count=1, vector_result_count=1,
            final_result_count=1, result_ids_json=[unit_id], latency_ms=5,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return {
            "retrieval_log_id": log.id,
            "answer": answer,
            "citations": citations
            if citations is not None
            else [{"knowledge_unit_id": unit_id, "quoted_content": "余额规则"}],
            "supported_claims": list(claims if claims is not None else []),
            "unsupported_claims": [],
            "open_questions": [],
            "answer_status": status,
            "degraded_reason": reason,
            "execution_metadata": {"execution_kind": "mock_model",
                                   "model_profile_id": kwargs.get("model_profile_id")},
        }

    monkeypatch.setattr(rag_evaluator, "grounded_answer", fake_grounded_answer)
    return captured


# ------------------------------------------------------------------ switch off (regression)


def test_judge_off_keeps_the_frozen_summary_contract(env, monkeypatch):
    with env() as db:
        profiles = _profiles(db)
        project_id, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="grounded", answer="余额规则：以合同为准。")

        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        summary = completed.summary_metrics_json

        assert set(summary) == FROZEN_SUMMARY_KEYS
        assert set(summary["metric_notes"]) == FROZEN_METRIC_NOTE_KEYS
        assert summary["recall_at_5"] == 1.0
        assert summary["answer_correctness_denominator"] == 2
        assert CALL_COUNT["value"] == 0, "the judge gateway must not be called while disabled"

        rows = list(db.scalars(
            select(RagEvaluationResult).where(RagEvaluationResult.evaluation_run_id == run.id)
        ))
        assert len(rows) == 2
        for row in rows:
            assert "faithfulness" not in row.execution_metadata_json
            assert "citation_support" not in row.execution_metadata_json


def test_judge_off_does_not_change_existing_metric_values(env, monkeypatch):
    """The degraded-answer path must keep reporting exactly what it did before ⑧."""

    with env() as db:
        profiles = _profiles(db)
        project_id, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="degraded", answer="待确认", reason="timeout")

        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        summary = completed.summary_metrics_json
        assert set(summary) == FROZEN_SUMMARY_KEYS
        assert summary["successful_query_count"] == 0
        assert summary["degraded_query_count"] == 2
        assert summary["groundedness"] == 0.0
        assert summary["answer_correctness"] == 0.0
        assert summary["answer_correctness_denominator"] == 0
        assert CALL_COUNT["value"] == 0


# ------------------------------------------------------------------ switch on


def test_judge_on_reports_faithfulness(env, monkeypatch):
    with env() as db:
        monkeypatch.setattr(get_settings(), "ragas_judge_enabled", True, raising=False)
        profiles = _profiles(db)
        project_id, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        _install_fake_answer(
            monkeypatch, status="grounded", answer="余额规则：以合同为准。",
            claims=["余额以合同为准。", "余额以口头约定为准。"],
        )
        _install_gateway(monkeypatch, lambda: _VerdictService(
            {"claims": [
                {"claim": "余额以合同为准。", "verdict": "supported", "reason": "引文支持"},
                {"claim": "余额以口头约定为准。", "verdict": "unsupported", "reason": "引文矛盾"},
            ]}
        ))

        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        summary = completed.summary_metrics_json

        assert set(summary) == FROZEN_SUMMARY_KEYS | JUDGE_SUMMARY_KEYS
        assert summary["faithfulness_denominator"] == 2
        assert summary["faithfulness"] == 0.5
        assert summary["unsupported_citation_ratio"] == 0.5
        # Retrieval/answer metrics keep their pre-⑧ values.
        assert summary["recall_at_5"] == 1.0
        assert summary["answer_correctness_denominator"] == 2
        assert set(summary["metric_notes"]) == FROZEN_METRIC_NOTE_KEYS | {
            "faithfulness", "unsupported_citation_ratio",
        }

        rows = list(db.scalars(
            select(RagEvaluationResult).where(RagEvaluationResult.evaluation_run_id == run.id)
        ))
        for row in rows:
            metadata = row.execution_metadata_json
            assert metadata["answer_status"] == "grounded"
            assert metadata["faithfulness"]["judged"] is True
            assert metadata["faithfulness"]["supported_count"] == 1
            assert metadata["faithfulness"]["unsupported_count"] == 1
            assert metadata["faithfulness"]["model_profile_id"] == profiles[0].id


def test_judge_on_gateway_failure_keeps_the_run_completed_and_metrics_intact(env, monkeypatch):
    with env() as db:
        monkeypatch.setattr(get_settings(), "ragas_judge_enabled", True, raising=False)
        profiles = _profiles(db)
        project_id, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="grounded", answer="余额规则：以合同为准。")
        _install_gateway(monkeypatch, _FailingService)

        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        summary = completed.summary_metrics_json

        assert completed.status == "completed"
        assert summary["failed_query_count"] == 0
        assert summary["successful_query_count"] == 2
        # Unjudged, so faithfulness has no denominator and must not masquerade as a clean 0.
        assert summary["faithfulness_denominator"] == 0
        assert summary["faithfulness"] == 0.0
        assert summary["recall_at_5"] == 1.0
        assert summary["answer_correctness_denominator"] == 2
        assert CALL_COUNT["value"] == 2

        rows = list(db.scalars(
            select(RagEvaluationResult).where(RagEvaluationResult.evaluation_run_id == run.id)
        ))
        for row in rows:
            judgement = row.execution_metadata_json["faithfulness"]
            assert judgement["degraded"] is True
            assert judgement["degraded_reason"] == "timeout"
            assert judgement["judged"] is False


def test_judge_on_degraded_answer_still_evaluates_the_run(env, monkeypatch):
    with env() as db:
        monkeypatch.setattr(get_settings(), "ragas_judge_enabled", True, raising=False)
        profiles = _profiles(db)
        project_id, run = _seed_run(db, cases=[1], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="degraded", answer="待确认", reason="timeout")
        _install_gateway(monkeypatch, lambda: _VerdictService(
            {"verdicts": [{"verdict": "supported", "reason": "引文支持"}]}
        ))

        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        summary = completed.summary_metrics_json
        assert completed.status == "completed"
        assert summary["degraded_query_count"] == 1
        assert summary["faithfulness_denominator"] == 1
        assert summary["faithfulness"] == 1.0


def test_judge_on_empty_answer_makes_no_model_call(env, monkeypatch):
    with env() as db:
        monkeypatch.setattr(get_settings(), "ragas_judge_enabled", True, raising=False)
        profiles = _profiles(db)
        project_id, run = _seed_run(db, cases=[1], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="grounded", answer="", claims=[""],
                             citations=[])

        def explode():  # pragma: no cover - must never be reached
            raise AssertionError("an empty answer must not reach the judge gateway")

        _install_gateway(monkeypatch, explode)
        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        summary = completed.summary_metrics_json
        assert summary["faithfulness_denominator"] == 0
        assert CALL_COUNT["value"] == 0


# ------------------------------------------------------------------ engine-level boundaries


def test_judge_faithfulness_is_skipped_entirely_while_disabled(env, monkeypatch):
    with env() as db:
        profiles = _profiles(db)
        _install_gateway(monkeypatch, lambda: _VerdictService({"verdicts": []}))
        result = asyncio.run(judge_faithfulness(db, answer="结论。", citations=[]))
        assert result["enabled"] is False
        assert result["judged"] is False
        assert result["skip_reason"] == "judge_disabled"
        assert CALL_COUNT["value"] == 0


def test_judge_faithfulness_handles_empty_and_unparseable_input(env, monkeypatch):
    with env() as db:
        monkeypatch.setattr(get_settings(), "ragas_judge_enabled", True, raising=False)
        profiles = _profiles(db)

        def explode():  # pragma: no cover
            raise AssertionError("an empty answer must not reach the judge gateway")

        _install_gateway(monkeypatch, explode)
        empty = asyncio.run(judge_faithfulness(db, answer="   ", citations=[]))
        assert empty["enabled"] is True and empty["judged"] is False
        assert empty["skip_reason"] == "empty_answer"
        assert CALL_COUNT["value"] == 0

        _install_gateway(monkeypatch, lambda: _VerdictService("not json"))
        unparsed = asyncio.run(judge_faithfulness(db, answer="余额以合同为准。", citations=[]))
        assert unparsed["judged"] is False
        assert unparsed["degraded"] is True
        assert unparsed["degraded_reason"] == "invalid_judgement"
        assert unparsed["claims_total"] == 1
