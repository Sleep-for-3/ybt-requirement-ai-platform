from datetime import UTC, datetime

from sqlalchemy import select

from app.models import RagEvaluationCase, RagEvaluationResult, RetrievalLog
from app.services.rag import grounded_answer


async def run_evaluation(db, run):
    run.status = "running"
    run.started_at = datetime.now(UTC)
    db.commit()
    cases = list(
        db.scalars(
            select(RagEvaluationCase).where(
                RagEvaluationCase.project_id == run.project_id,
                RagEvaluationCase.enabled.is_(True),
            )
        ).all()
    )
    metrics = []
    top_k = min(max(int((run.retrieval_config_json or {}).get("top_k", 10)), 10), 50)
    for case in cases:
        started = datetime.now(UTC)
        answer = await grounded_answer(
            db,
            run.project_id,
            case.query_text,
            target_field_id=case.target_field_id,
            scenario_id=case.scenario_id,
            top_k=top_k,
        )
        retrieval_log = db.get(RetrievalLog, answer["retrieval_log_id"])
        retrieved = list(retrieval_log.result_ids_json or []) if retrieval_log else []
        expected = list(case.expected_knowledge_unit_ids_json or [])
        recall_5 = _recall(retrieved[:5], expected)
        recall_10 = _recall(retrieved[:10], expected)
        ranks = [index for index, item in enumerate(retrieved, 1) if item in expected]
        reciprocal_rank = 1 / min(ranks) if ranks else 0.0
        evidence_text = " ".join(
            [answer["answer"]]
            + [str(item.get("quoted_content") or "") for item in answer["citations"]]
        ).lower()
        source_hit = _expected_hit(evidence_text, case.expected_source_system, ranks)
        table_hit = _expected_hit(evidence_text, case.expected_table_name, ranks)
        field_hit = _expected_hit(evidence_text, case.expected_field_name, ranks)
        keywords = list(case.expected_answer_keywords_json or [])
        keyword_coverage = (
            sum(1 for item in keywords if item.lower() in evidence_text) / len(keywords)
            if keywords
            else 1.0
        )
        citation_coverage = (
            len({item["knowledge_unit_id"] for item in answer["citations"]} & set(expected)) / len(expected)
            if expected
            else (1.0 if answer["citations"] else 0.0)
        )
        groundedness = 1.0 if answer["citations"] and not answer["unsupported_claims"] else 0.0
        open_question_accuracy = 1.0 if answer["open_questions"] else 0.0
        latency_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        db.add(
            RagEvaluationResult(
                evaluation_run_id=run.id,
                evaluation_case_id=case.id,
                retrieved_unit_ids_json=retrieved,
                generated_answer=answer["answer"],
                citations_json=answer["citations"],
                recall_at_k=recall_5,
                reciprocal_rank=reciprocal_rank,
                source_hit=source_hit,
                citation_coverage=citation_coverage,
                groundedness_score=groundedness,
                keyword_coverage=keyword_coverage,
                latency_ms=latency_ms,
            )
        )
        metrics.append(
            {
                "recall_at_5": recall_5,
                "recall_at_10": recall_10,
                "reciprocal_rank": reciprocal_rank,
                "source_hit": float(source_hit),
                "table_hit": float(table_hit),
                "field_hit": float(field_hit),
                "citation_coverage": citation_coverage,
                "groundedness": groundedness,
                "keyword_coverage": keyword_coverage,
                "open_question_accuracy": open_question_accuracy,
                "latency_ms": latency_ms,
            }
        )
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    run.summary_metrics_json = {
        "case_count": len(metrics),
        "recall_at_5": _average(metrics, "recall_at_5"),
        "recall_at_10": _average(metrics, "recall_at_10"),
        "mrr": _average(metrics, "reciprocal_rank"),
        "source_hit_rate": _average(metrics, "source_hit"),
        "table_hit_rate": _average(metrics, "table_hit"),
        "field_hit_rate": _average(metrics, "field_hit"),
        "citation_coverage": _average(metrics, "citation_coverage"),
        "groundedness": _average(metrics, "groundedness"),
        "keyword_coverage": _average(metrics, "keyword_coverage"),
        "open_question_accuracy": _average(metrics, "open_question_accuracy"),
        "average_latency_ms": _average(metrics, "latency_ms"),
    }
    db.commit()
    db.refresh(run)
    return run


def _recall(retrieved: list[int], expected: list[int]) -> float:
    return len(set(retrieved) & set(expected)) / len(expected) if expected else 1.0


def _expected_hit(text: str, expected: str | None, ranks: list[int]) -> bool:
    return expected.lower() in text if expected else bool(ranks)


def _average(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / len(items) if items else 0.0
