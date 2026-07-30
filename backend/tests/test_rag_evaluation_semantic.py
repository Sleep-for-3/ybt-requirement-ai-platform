import asyncio

from app.models import Project, RagEvaluationCase, RagEvaluationRun, RetrievalLog
from app.services.evaluation import rag_evaluator


def test_semantic_evaluation_records_modes_latency_percentiles_and_quality_metrics(
    db_session,
    monkeypatch,
):
    project = Project(name="评测项目")
    db_session.add(project)
    db_session.flush()
    cases = [
        RagEvaluationCase(
            project_id=project.id,
            case_name=f"case-{index}",
            case_type="retrieval",
            query_text=f"问题-{index}",
            expected_knowledge_unit_ids_json=[index],
            expected_answer_keywords_json=["余额"],
            enabled=True,
        )
        for index in (10, 30)
    ]
    run = RagEvaluationRun(
        project_id=project.id,
        run_name="formal-hybrid",
        retrieval_config_json={"retrieval_mode": "formal_hybrid", "top_k": 10},
        status="pending",
    )
    db_session.add_all([*cases, run])
    db_session.commit()
    db_session.refresh(run)

    async def fake_grounded_answer(db, project_id, query, **kwargs):
        unit_id = int(query.rsplit("-", 1)[1])
        log = RetrievalLog(
            project_id=project_id,
            query_text=query,
            query_type=kwargs["retrieval_mode"],
            filters_json={},
            retrieval_strategy=kwargs["retrieval_mode"],
            keyword_result_count=1,
            vector_result_count=1,
            final_result_count=1,
            result_ids_json=[unit_id],
            latency_ms=unit_id,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return {
            "retrieval_log_id": log.id,
            "answer": "余额规则",
            "citations": [{"knowledge_unit_id": unit_id, "quoted_content": "余额规则"}],
            "unsupported_claims": [],
            "open_questions": [],
        }

    monkeypatch.setattr(rag_evaluator, "grounded_answer", fake_grounded_answer)

    completed = asyncio.run(rag_evaluator.run_evaluation(db_session, run))
    metrics = completed.summary_metrics_json

    assert completed.retrieval_config_json["retrieval_mode"] == "hybrid"
    assert completed.retrieval_config_json["dataset_version"]
    assert metrics["recall_at_5"] == 1.0
    assert metrics["recall_at_10"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["citation_coverage"] == 1.0
    assert metrics["answer_correctness"] == 1.0
    assert metrics["retrieval_latency_p50_ms"] == 20.0
    assert metrics["retrieval_latency_p95_ms"] == 29.0
    assert metrics["failed_query_count"] == 0
