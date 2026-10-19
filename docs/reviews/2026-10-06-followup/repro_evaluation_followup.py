"""Read-only product-source follow-up: in-memory SQLite and spy model/retriever.

Writes results only next to this script; never touches business DB/network/model.
"""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
for key, value in {
    "DATABASE_URL": "sqlite:///:memory:", "ENVIRONMENT": "development",
    "AUTH_MODE": "required", "APP_SECRET_KEY": "isolated-followup-only",
    "JWT_SECRET_KEY": "isolated-review-jwt-key-at-least-32-characters",
    "TASK_QUEUE_PROVIDER": "inline", "LLM_PROVIDER": "mock", "LLM_BASE_URL": "",
    "LLM_MODEL": "", "LLM_API_KEY_ENV_NAME": "", "EMBEDDING_PROVIDER": "mock",
    "EMBEDDING_BASE_URL": "", "EMBEDDING_MODEL": "", "EMBEDDING_DIMENSION": "0",
    "EMBEDDING_API_KEY_ENV_NAME": "", "VECTOR_STORE_PROVIDER": "mock", "MILVUS_URI": "",
}.items():
    os.environ[key] = value

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models import ModelProfile, Project, RagEvaluationCase, RagEvaluationRun, RagEvaluationResult, RetrievalLog
from app.services.evaluation import rag_evaluator
from app.services.llm.base import LLMRuntimeError
from app.services.llm.execution_metadata import build_execution_metadata

gas = importlib.import_module("app.services.rag.grounded_answer_service")
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
report = {"scope": "actual evaluator->grounded_answer->runtime, retriever/model boundary spies; memory SQLite"}
queries = []
captured = []
state = {}

def fake_search(self, project_id, query, *args, **kwargs):
    queries.append(query)
    log = RetrievalLog(project_id=project_id, query_text=query, query_type="keyword_only", filters_json={},
                       retrieval_strategy="keyword_only", keyword_result_count=1, vector_result_count=0,
                       final_result_count=1, result_ids_json=[1], latency_ms=1)
    self.db.add(log)
    self.db.commit()
    self.db.refresh(log)
    return log, [{"knowledge_unit_id": 1, "document_id": 1, "document_version_id": 1,
                  "content": "余额规则 ECIF CUSTOMER BALANCE", "confidentiality_level": "internal",
                  "rerank_score": 1, "authority_rank": 6, "knowledge_type": "regulatory_policy"}]

async def spy_model(db, project_id, runtime, *args, **kwargs):
    captured.append({"model_profile_id": runtime.model_profile_id, "model": runtime.model_name})
    state["calls"] = state.get("calls", 0) + 1
    if state.get("mutate") and state["calls"] == 1:
        with Session(engine) as other:
            case = other.get(RagEvaluationCase, state["mutate"])
            case.query_text = "并发修改后的第二个问题"
            case.expected_answer_keywords_json = ["与初始真值不同"]
            other.commit()
    if state.get("partial_degrade") and state["calls"] == 2:
        raise LLMRuntimeError("synthetic timeout", error_type="timeout")
    answer_text = "请确认其他业务" if state.get("wrong_answer") else "余额规则"
    output = {"answer": answer_text, "confidence_level": "high", "supported_claims": [answer_text],
              "unsupported_claims": [], "open_questions": []}
    return output, build_execution_metadata(runtime, output=output)

with Session(engine) as db:
    project = Project(name="isolated C06-C08 follow-up")
    profiles = [ModelProfile(profile_name=f"followup-{name}", provider_type="mock", model_name=name,
                             enabled=True, local_only=True, config_json={}) for name in ("model-A", "model-B")]
    db.add_all([project, *profiles])
    db.flush()
    cases = [RagEvaluationCase(project_id=project.id, case_name=f"case-{i}", case_type="retrieval",
        query_text=f"初始问题-{i}", expected_knowledge_unit_ids_json=[1], expected_source_system="ECIF",
        expected_table_name="CUSTOMER", expected_field_name="BALANCE", expected_answer_keywords_json=["余额"],
        enabled=True) for i in (1, 2)]
    db.add_all(cases)
    db.commit()
    second_case_id = cases[1].id
    with patch.object(gas.HybridRetriever, "search", fake_search), \
         patch.object(gas, "validate_citations", lambda *a, **k: None), \
         patch.object(gas, "_index_freshness", lambda *a, **k: {"formal_index_current": True}), \
         patch.object(gas, "execute_runtime_chat_with_metadata", spy_model):
        def execute(name, profile_id=None, **flags):
            state.clear(); state.update(flags); captured.clear(); queries.clear()
            run = RagEvaluationRun(project_id=project.id, run_name=name, status="pending",
                model_profile_id=profile_id, retrieval_config_json={"retrieval_mode": "keyword_only"})
            db.add(run); db.commit()
            asyncio.run(rag_evaluator.run_evaluation(db, run))
            rows = list(db.scalars(select(RagEvaluationResult).where(RagEvaluationResult.evaluation_run_id == run.id)))
            return run, rows

        selected, rows = execute("explicit B", profiles[1].id)
        report["explicit_selection_fixed"] = {"recorded": selected.retrieval_config_json["chat_model"],
            "calls": list(captured), "pass": all(x["model_profile_id"] == profiles[1].id for x in captured)}

        default, rows = execute("no explicit profile")
        report["default_selection_metadata_mismatch"] = {
            "recorded_chat_model": default.retrieval_config_json["chat_model"],
            "recorded_chat_profile_id": default.retrieval_config_json["chat_profile_id"],
            "actual_runtime": list(captured), "result_metadata": rows[0].execution_metadata_json}

        partial, rows = execute("partial timeout", partial_degrade=True)
        report["partial_degrade_ui_missing_denominator"] = {"status": partial.status,
            "metrics": partial.summary_metrics_json,
            "result_statuses": [x.execution_metadata_json.get("answer_status") for x in rows]}

        wrong, rows = execute("answer omits expected keyword", wrong_answer=True)
        report["citation_keyword_still_scores_as_answer"] = {"metrics": wrong.summary_metrics_json,
            "answer": rows[0].generated_answer, "citation": rows[0].citations_json}

        def controlled_policy_denial(*args, **kwargs):
            raise ValueError("controlled data classification policy denial")
        with patch.object(gas, "prepare_model_input", controlled_policy_denial):
            denied, rows = execute("data classification blocks model")
        report["policy_denial_reason_is_overwritten"] = {
            "answer": rows[0].generated_answer,
            "result_execution_metadata": rows[0].execution_metadata_json,
            "degraded_count": denied.summary_metrics_json["degraded_query_count"],
        }

        original_hash = rag_evaluator._dataset_version(list(db.scalars(select(RagEvaluationCase))))
        concurrent, rows = execute("concurrent annotation edit", mutate=second_case_id)
        report["dataset_snapshot_not_frozen"] = {
            "initial_dataset_hash": original_hash,
            "run_dataset_hash": concurrent.retrieval_config_json["dataset_version"],
            "actual_executed_queries": list(queries),
            "live_cases_hash": rag_evaluator._dataset_version(list(db.scalars(select(RagEvaluationCase)))),
            "run_has_full_case_snapshot": any("snapshot" in k for k in concurrent.retrieval_config_json),
            "result_points_to_mutable_case_id": rows[1].evaluation_case_id,
            "run_config_keys": sorted(concurrent.retrieval_config_json),
        }

engine.dispose()
out = HERE / "evaluation-followup-result.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
