"""C06 / C07 / C08: evaluation model fidelity, degraded scoring and dataset versioning.

Reproduction baseline: ``docs/reviews/2026-10-06/evaluation-repro-result.json``.

These tests drive the **real** evaluation entry points:

* ``get_prompt_runtime`` -- the runtime actually built and executed;
* ``run_evaluation`` -- the real scoring/summary path, with ``grounded_answer`` replaced at the
  model boundary (a spy), so no real model is ever called;
* ``_dataset_version`` -- the real digest function.

Isolated: in-memory/temp SQLite, mocked model boundary, no business database, no real model.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    ModelProfile,
    Project,
    RagEvaluationCase,
    RagEvaluationResult,
    RagEvaluationRun,
    RetrievalLog,
)
from app.services.evaluation import rag_evaluator
from app.services.llm.prompt_runtime import get_prompt_runtime


@pytest.fixture()
def env(tmp_path):
    url = "sqlite:///" + (tmp_path / "eval.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=None)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _profiles(db, *, count=2):
    profiles = []
    for index in range(1, count + 1):
        profile = ModelProfile(
            profile_name=f"profile-{index}", provider_type="mock", model_name=f"model-{chr(64 + index)}",
            enabled=True, local_only=True, supports_structured_output=True,
            max_context_tokens=8192, temperature=0.0, config_json={}, created_by="c06",
        )
        db.add(profile)
        profiles.append(profile)
    db.commit()
    for profile in profiles:
        db.refresh(profile)
    return profiles


# --------------------------------------------------------------------------- C06


def test_c06_an_explicitly_selected_profile_is_the_one_built(env):
    """Reproduction: profile A has the smaller id, the caller selects B, runtime must be B."""

    with env() as db:
        profile_a, profile_b = _profiles(db)
        assert profile_a.id < profile_b.id, "fixture must reproduce 'A has the smaller id'"

        # Pre-fix behaviour: no selection -> lowest id (A). Kept as the documented default.
        default_runtime = get_prompt_runtime(db, "regulatory_field_explanation")
        assert default_runtime.model_profile_id == profile_a.id

        selected = get_prompt_runtime(db, "regulatory_field_explanation",
                                      model_profile_id=profile_b.id)
        assert selected.model_profile_id == profile_b.id
        assert selected.model_name == profile_b.model_name, (
            "the runtime must execute the selected profile, not the default one")


def test_c06_a_missing_or_disabled_profile_is_refused(env):
    with env() as db:
        profile_a, profile_b = _profiles(db)
        with pytest.raises(ValueError):
            get_prompt_runtime(db, "regulatory_field_explanation", model_profile_id=999999)
        profile_b.enabled = False
        db.commit()
        with pytest.raises(ValueError):
            get_prompt_runtime(db, "regulatory_field_explanation", model_profile_id=profile_b.id)


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
    project = Project(name="C07 评测项目")
    db.add(project)
    db.flush()
    rows = [_case(project.id, index) for index in cases]
    run = RagEvaluationRun(
        project_id=project.id, run_name="c07", model_profile_id=profile_id,
        retrieval_config_json={"retrieval_mode": mode, "top_k": 10},
        status="pending", started_at=datetime.now(UTC), created_by="c07",
    )
    db.add_all([*rows, run])
    db.commit()
    db.refresh(run)
    return project.id, run


def _install_fake_answer(monkeypatch, *, status: str, answer: str, reason: str | None = None):
    """Replace only the model boundary; everything else stays the real evaluation code."""

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
            "citations": [{"knowledge_unit_id": unit_id, "quoted_content": "余额规则"}],
            "unsupported_claims": [],
            "open_questions": [],
            "answer_status": status,
            "degraded_reason": reason,
            "execution_metadata": {"execution_kind": "degraded" if status != "grounded" else "model",
                                   "model_profile_id": kwargs.get("model_profile_id")},
        }

    monkeypatch.setattr(rag_evaluator, "grounded_answer", fake_grounded_answer)
    return captured


def test_c07_a_degraded_answer_is_not_scored_as_a_correct_answer(env, monkeypatch):
    """Reproduction: model timeout -> run 'completed', successful=1, groundedness=1, correctness=1."""

    with env() as db:
        profiles = _profiles(db, count=1)
        _, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        captured = _install_fake_answer(
            monkeypatch, status="degraded",
            answer="模型生成暂时不可用，以下为检索到的证据，结论待确认。",
            reason="timeout")
        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        metrics = completed.summary_metrics_json

        # Retrieval quality must stay intact (it is still measured).
        assert metrics["recall_at_5"] == 1.0
        assert metrics["mrr"] == 1.0
        # ... but a degraded answer is NOT a successful, correct answer.
        assert metrics["successful_query_count"] == 0, metrics
        assert metrics["retrieval_only_query_count"] == 2, metrics
        assert metrics["degraded_query_count"] == 2, metrics
        assert metrics["answer_correctness"] == 0.0, metrics
        assert metrics["groundedness"] == 0.0, metrics
        assert metrics["answer_correctness_denominator"] == 0, metrics

        # Execution facts must be persisted per case (previously execution_metadata was null).
        rows = list(db.scalars(select(RagEvaluationResult).where(
            RagEvaluationResult.evaluation_run_id == run.id)))
        assert rows, "results were not persisted"
        assert all(row.execution_metadata_json.get("answer_status") == "degraded" for row in rows)
        assert all(row.execution_metadata_json.get("degraded_reason") == "timeout" for row in rows)

        # C06: the run's selected profile reached the model boundary.
        assert all(call.get("model_profile_id") == profiles[0].id
                   for call in captured["calls"]), captured["calls"]


def test_c07_a_normal_answer_still_scores_normally(env, monkeypatch):
    with env() as db:
        profiles = _profiles(db, count=1)
        _, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="grounded", answer="余额规则：以合同为准。")
        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        metrics = completed.summary_metrics_json
        assert metrics["successful_query_count"] == 2, metrics
        assert metrics["degraded_query_count"] == 0, metrics
        assert metrics["answer_correctness"] == 1.0, metrics
        assert metrics["groundedness"] == 1.0, metrics
        assert metrics["answer_correctness_denominator"] == 2, metrics


def test_c07_a_partially_degraded_run_cannot_show_a_full_score(env, monkeypatch):
    """Half the cases degrade: the run must not report an overall perfect answer score."""

    with env() as db:
        profiles = _profiles(db, count=1)
        _, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        state = {"index": 0}

        async def fake(db, project_id, query, **kwargs):
            state["index"] += 1
            degraded = state["index"] % 2 == 0
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
                "answer": "模型生成暂时不可用" if degraded else "余额规则",
                "citations": [{"knowledge_unit_id": unit_id, "quoted_content": "余额规则"}],
                "unsupported_claims": [], "open_questions": [],
                "answer_status": "degraded" if degraded else "grounded",
                "execution_metadata": {},
            }

        monkeypatch.setattr(rag_evaluator, "grounded_answer", fake)
        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        metrics = completed.summary_metrics_json
        assert metrics["case_count"] == 2
        assert metrics["successful_query_count"] == 1, metrics
        assert metrics["degraded_query_count"] == 1, metrics
        # Averages cover generated answers only, and the denominator is stated.
        assert metrics["answer_correctness_denominator"] == 1, metrics
        assert metrics["answer_correctness"] == 1.0
        # Retrieval metrics still cover both executed queries.
        assert metrics["recall_at_5"] == 1.0


def test_c07_a_failed_query_records_its_error_metadata(env, monkeypatch):
    with env() as db:
        profiles = _profiles(db, count=1)
        _, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)

        async def boom(db, project_id, query, **kwargs):
            if query.endswith("-2"):
                raise RuntimeError("synthetic retrieval failure")
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
                "retrieval_log_id": log.id, "answer": "余额规则",
                "citations": [{"knowledge_unit_id": unit_id, "quoted_content": "余额规则"}],
                "unsupported_claims": [], "open_questions": [], "answer_status": "grounded",
                "execution_metadata": {},
            }

        monkeypatch.setattr(rag_evaluator, "grounded_answer", boom)
        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        metrics = completed.summary_metrics_json
        assert metrics["failed_query_count"] == 1, metrics
        assert metrics["successful_query_count"] == 1, metrics
        rows = list(db.scalars(select(RagEvaluationResult).where(
            RagEvaluationResult.evaluation_run_id == run.id)))
        failed = [row for row in rows if row.error_message]
        assert len(failed) == 1
        assert failed[0].execution_metadata_json.get("answer_status") == "error"


# --------------------------------------------------------------------------- C08


def _dataset_case(**overrides):
    values = {
        "id": 1, "query_text": "问题-1", "enabled": True,
        "expected_knowledge_unit_ids_json": [10],
        "expected_answer_keywords_json": ["余额"],
        "expected_source_system": "核心",
        "expected_table_name": "SRC_LOAN",
        "expected_field_name": "loan_bal",
        "target_field_id": 5,
        "scenario_id": 7,
    }
    values.update(overrides)

    class _Case:
        pass

    case = _Case()
    for key, value in values.items():
        setattr(case, key, value)
    return case


@pytest.mark.parametrize("field,value", [
    ("expected_source_system", "信贷"),
    ("expected_table_name", "SRC_CUST"),
    ("expected_field_name", "cust_no"),
    ("expected_answer_keywords_json", ["余额", "口径"]),
    ("target_field_id", 9),
    ("scenario_id", 11),
    ("query_text", "问题-1（改写）"),
    ("expected_knowledge_unit_ids_json", [10, 11]),
])
def test_c08_every_semantic_change_changes_the_dataset_version(field, value):
    base = [_dataset_case()]
    changed = [_dataset_case(**{field: value})]
    assert rag_evaluator._dataset_version(base) != rag_evaluator._dataset_version(changed), field


def test_c08_row_order_does_not_change_the_version():
    first = _dataset_case(id=1)
    second = _dataset_case(id=2, query_text="问题-2",
                           expected_knowledge_unit_ids_json=[20])
    assert (rag_evaluator._dataset_version([first, second])
            == rag_evaluator._dataset_version([second, first])), (
        "an equivalent dataset must hash identically regardless of row order")


def test_c08_the_version_is_schema_tagged():
    assert rag_evaluator.DATASET_VERSION_SCHEMA == "rag-eval-dataset-v2"
    assert rag_evaluator._dataset_version([_dataset_case()]) != ""


def test_c08_an_edited_annotation_does_not_change_already_recorded_evidence(env, monkeypatch):
    """A run binds its own dataset snapshot; later edits cannot rewrite what ran."""

    with env() as db:
        profiles = _profiles(db, count=1)
        project_id, run = _seed_run(db, cases=[1, 2], profile_id=profiles[0].id)
        _install_fake_answer(monkeypatch, status="grounded", answer="余额规则")
        completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
        recorded = completed.retrieval_config_json["dataset_version"]

        # The annotation changes *after* the run finished.
        case = db.scalar(select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == project_id).order_by(RagEvaluationCase.id))
        case.expected_table_name = "CHANGED_AFTER_RUN"
        db.commit()

        assert completed.retrieval_config_json["dataset_version"] == recorded, (
            "already-recorded run evidence must keep pointing at the snapshot it actually used")
        assert rag_evaluator._dataset_version([case]) != recorded, (
            "the dataset version itself must move when the annotation changes")
