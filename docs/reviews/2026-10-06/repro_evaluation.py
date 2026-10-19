"""Read-only product review reproductions. In-memory SQLite, no network/model/broker.

Run with backend/.venv/Scripts/python.exe from any working directory.
This file does not modify application sources or an existing database.
"""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
for key, value in {
    "DATABASE_URL": "sqlite:///:memory:",
    "ENVIRONMENT": "development",
    "AUTH_MODE": "required",
    "APP_SECRET_KEY": "isolated-review-only",
    "JWT_SECRET_KEY": "isolated-review-jwt-key-at-least-32-characters",
    "TASK_QUEUE_PROVIDER": "inline",
    "LLM_PROVIDER": "mock",
    "LLM_BASE_URL": "",
    "LLM_MODEL": "",
    "LLM_API_KEY_ENV_NAME": "",
    "EMBEDDING_PROVIDER": "mock",
    "EMBEDDING_BASE_URL": "",
    "EMBEDDING_MODEL": "",
    "EMBEDDING_DIMENSION": "0",
    "EMBEDDING_API_KEY_ENV_NAME": "",
    "VECTOR_STORE_PROVIDER": "mock",
    "MILVUS_URI": "",
}.items():
    os.environ[key] = value

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models import ModelProfile, Project, RagEvaluationCase, RagEvaluationResult, RagEvaluationRun, RetrievalLog
from app.services.evaluation import rag_evaluator
from app.services.llm.base import LLMRuntimeError

gas = importlib.import_module("app.services.rag.grounded_answer_service")
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
report = {}

def fake_search(self, project_id, query, *args, **kwargs):
    log = RetrievalLog(project_id=project_id, query_text=query, query_type="hybrid", filters_json={},
                       retrieval_strategy="hybrid", keyword_result_count=1, vector_result_count=0,
                       final_result_count=1, result_ids_json=[1], latency_ms=1)
    self.db.add(log)
    self.db.commit()
    self.db.refresh(log)
    return log, [{"knowledge_unit_id": 1, "document_id": 1, "document_version_id": 1,
                  "content": "余额规则 ECIF CUSTOMER BALANCE", "confidentiality_level": "internal",
                  "rerank_score": 1, "authority_rank": 6, "knowledge_type": "regulatory_policy"}]

with Session(engine) as db:
    project = Project(name="isolated review")
    profiles = [ModelProfile(profile_name=f"review-{name}", provider_type="mock", model_name=name,
                             enabled=True, local_only=True, config_json={}) for name in ("model-A", "model-B")]
    db.add_all([project, *profiles])
    db.flush()
    case = RagEvaluationCase(project_id=project.id, case_name="balance", case_type="retrieval",
        query_text="余额怎么计算", expected_knowledge_unit_ids_json=[1],
        expected_source_system="ECIF", expected_table_name="CUSTOMER", expected_field_name="BALANCE",
        expected_answer_keywords_json=["余额"], enabled=True)
    db.add(case)
    db.commit()
    captured = []
    async def spy_model(db, project_id, runtime, *args, **kwargs):
        captured.append({"model_profile_id": runtime.model_profile_id, "model": runtime.model_name})
        return {"answer": "余额规则", "confidence_level": "high", "supported_claims": ["余额规则"],
                "unsupported_claims": [], "open_questions": []}, {"execution_kind": "mock_model"}
    async def timeout_model(*args, **kwargs):
        raise LLMRuntimeError("synthetic timeout", error_type="timeout")

    with patch.object(gas.HybridRetriever, "search", fake_search), \
         patch.object(gas, "validate_citations", lambda *a, **k: None), \
         patch.object(gas, "_index_freshness", lambda *a, **k: {"formal_index_current": True}):
        run = RagEvaluationRun(project_id=project.id, run_name="requested-B", status="pending",
                               model_profile_id=profiles[1].id, retrieval_config_json={"retrieval_mode": "keyword_only"})
        db.add(run)
        db.commit()
        with patch.object(gas, "execute_runtime_chat_with_metadata", spy_model):
            asyncio.run(rag_evaluator.run_evaluation(db, run))
        report["model_selection"] = {"requested_profile_id": profiles[1].id,
            "recorded_chat_model": run.retrieval_config_json["chat_model"], "actual_runtime": captured,
            "mismatch": captured[0]["model_profile_id"] != profiles[1].id}

        degraded_run = RagEvaluationRun(project_id=project.id, run_name="timeout", status="pending", retrieval_config_json={})
        db.add(degraded_run)
        db.commit()
        with patch.object(gas, "execute_runtime_chat_with_metadata", timeout_model):
            asyncio.run(rag_evaluator.run_evaluation(db, degraded_run))
        result = db.scalar(select(RagEvaluationResult).where(RagEvaluationResult.evaluation_run_id == degraded_run.id))
        report["degraded_scoring"] = {"answer": result.generated_answer, "run_status": degraded_run.status,
            "metrics": {key: degraded_run.summary_metrics_json[key] for key in (
                "successful_query_count", "failed_query_count", "groundedness", "answer_correctness", "keyword_coverage")},
            "execution_metadata_persisted": result.execution_metadata_json}

    base = dict(id=1, query_text="same question", expected_knowledge_unit_ids_json=[1],
        expected_source_system="ECIF", expected_table_name="CUSTOMER", expected_field_name="BALANCE",
        expected_answer_keywords_json=["余额"], target_field_id=1, scenario_id=1, case_type="retrieval", enabled=True)
    before = rag_evaluator._dataset_version([SimpleNamespace(**base)])
    unchanged = []
    for field, value in {"expected_source_system": "CORE", "expected_table_name": "LOAN", "expected_field_name": "AMOUNT",
        "expected_answer_keywords_json": ["本金"], "target_field_id": 2, "scenario_id": 2}.items():
        altered = {**base, field: value}
        if rag_evaluator._dataset_version([SimpleNamespace(**altered)]) == before:
            unchanged.append(field)
    second = {**base, "id": 2, "query_text": "second question"}
    report["dataset_hash"] = {"semantic_changes_do_not_change_version": unchanged,
        "row_order_changes_version": rag_evaluator._dataset_version([SimpleNamespace(**base), SimpleNamespace(**second)])
            != rag_evaluator._dataset_version([SimpleNamespace(**second), SimpleNamespace(**base)])}

print(json.dumps(report, ensure_ascii=False, indent=2))
engine.dispose()
