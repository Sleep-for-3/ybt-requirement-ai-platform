import hashlib
import json
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.settings import get_settings
from app.models import (
    ModelCallLog,
    ModelProfile,
    RagEvaluationCase,
    RagEvaluationResult,
    RetrievalLog,
)
from app.services.rag import grounded_answer
from app.services.semantic_index.versioning import get_active_index_version


async def run_evaluation(db, run):
    run.status = "running"
    run.started_at = datetime.now(UTC)
    db.commit()
    cases = list(db.scalars(
        select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == run.project_id,
            RagEvaluationCase.enabled.is_(True),
        )
    ).all())
    config = dict(run.retrieval_config_json or {})
    retrieval_mode = _retrieval_mode(config.get("retrieval_mode", "hybrid"))
    top_k = min(max(int(config.get("top_k", 10)), 10), 50)
    active_index = get_active_index_version(db, run.project_id)
    settings = get_settings()
    chat_profile = db.get(ModelProfile, run.model_profile_id) if run.model_profile_id else None
    config.update({
        "dataset_version": _dataset_version(cases),
        "embedding_provider": active_index.provider if active_index else settings.embedding_provider,
        "embedding_model": active_index.model_name if active_index else settings.embedding_model or None,
        "vector_dimension": active_index.vector_dimension if active_index else settings.embedding_dimension or None,
        "index_version": active_index.id if active_index else None,
        "milvus_collection": active_index.collection_name if active_index else None,
        "retrieval_mode": retrieval_mode,
        "top_k": top_k,
        "keyword_weight": settings.hybrid_keyword_weight,
        "vector_weight": settings.hybrid_vector_weight,
        "chat_provider": chat_profile.provider_type if chat_profile else settings.llm_provider,
        # C06: record what was actually executed -- provider/model **and** the resolved profile id --
        # instead of only the environment default.
        "chat_model": chat_profile.model_name if chat_profile else settings.llm_model or None,
        "chat_profile_id": run.model_profile_id,
        "executed_at": datetime.now(UTC).isoformat(),
    })
    run.retrieval_config_json = config
    db.commit()

    metrics = []
    failed_query_count = 0
    degraded_query_count = 0
    total_token_usage = 0
    for case in cases:
        started = time.perf_counter()
        try:
            answer = await grounded_answer(
                db,
                run.project_id,
                case.query_text,
                interactive=False,
                target_field_id=case.target_field_id,
                scenario_id=case.scenario_id,
                top_k=top_k,
                retrieval_mode=retrieval_mode,
                # C06: always pass the run's selection explicitly. ``None`` means "no explicit
                # selection", in which case the resolved profile id is still recorded below.
                model_profile_id=run.model_profile_id,
            )
            retrieval_log = db.get(RetrievalLog, answer["retrieval_log_id"])
            retrieved = list(retrieval_log.result_ids_json or []) if retrieval_log else []
            expected = list(case.expected_knowledge_unit_ids_json or [])
            recall_5 = _recall(retrieved[:5], expected)
            recall_10 = _recall(retrieved[:10], expected)
            ranks = [index for index, item in enumerate(retrieved, 1) if item in expected]
            reciprocal_rank = 1 / min(ranks) if ranks else 0.0
            # C07: distinguish **retrieval quality** from **generation availability** and from
            # **answer quality**. A degraded answer (model unavailable) still has valid retrieval
            # metrics, but it must never be scored as a successful, correct answer: matching
            # keywords inside the degraded boilerplate does not prove a generated answer is right.
            answer_status = str(answer.get("answer_status") or "grounded")
            generation_available = answer_status == "grounded"
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
                if keywords else 1.0
            )
            citation_coverage = (
                len({item["knowledge_unit_id"] for item in answer["citations"]} & set(expected))
                / len(expected)
                if expected else (1.0 if answer["citations"] else 0.0)
            )
            groundedness = (
                1.0 if answer["citations"] and not answer["unsupported_claims"] else 0.0
            )
            if generation_available:
                answer_correctness = (
                    keyword_coverage * 0.7 + citation_coverage * 0.3
                    if keywords else (groundedness * 0.7 + citation_coverage * 0.3)
                )
            else:
                # No generated answer -> no answer-quality score. Retrieval metrics below stay intact.
                answer_correctness = 0.0
                groundedness = 0.0
                degraded_query_count += 1
            total_latency_ms = max(0, int((time.perf_counter() - started) * 1000))
            retrieval_latency_ms = retrieval_log.latency_ms if retrieval_log else total_latency_ms
            answer_latency_ms = max(0, total_latency_ms - retrieval_latency_ms)
            call_logs = list(db.scalars(select(ModelCallLog).where(
                ModelCallLog.retrieval_log_id == (retrieval_log.id if retrieval_log else -1)
            )).all())
            token_usage = sum(
                int((item.token_usage_json or {}).get("total_tokens", 0))
                for item in call_logs
            )
            total_token_usage += token_usage
            db.add(RagEvaluationResult(
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
                latency_ms=total_latency_ms,
                # C07: persist the execution facts (profile/model actually used + degraded reason).
                execution_metadata_json={
                    **(answer.get("execution_metadata") or {}),
                    "answer_status": answer_status,
                    "degraded_reason": answer.get("degraded_reason"),
                },
            ))
            metrics.append({
                "recall_at_5": recall_5,
                "recall_at_10": recall_10,
                "reciprocal_rank": reciprocal_rank,
                "source_hit": float(source_hit),
                "table_hit": float(table_hit),
                "field_hit": float(field_hit),
                "citation_coverage": citation_coverage,
                "groundedness": groundedness,
                "answer_correctness": answer_correctness,
                "keyword_coverage": keyword_coverage,
                "generation_available": float(generation_available),
                "retrieval_latency_ms": retrieval_latency_ms,
                "answer_latency_ms": answer_latency_ms,
                "total_latency_ms": total_latency_ms,
            })
        except Exception as exc:
            db.rollback()
            run = db.get(type(run), run.id)
            failed_query_count += 1
            db.add(RagEvaluationResult(
                evaluation_run_id=run.id,
                evaluation_case_id=case.id,
                retrieved_unit_ids_json=[],
                generated_answer=None,
                citations_json=[],
                recall_at_k=0,
                reciprocal_rank=0,
                source_hit=False,
                citation_coverage=0,
                groundedness_score=0,
                keyword_coverage=0,
                latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
                error_message=f"{type(exc).__name__}: evaluation query failed",
                # C07: a failed query also has no generated answer; record why.
                execution_metadata_json={"answer_status": "error",
                                         "degraded_reason": type(exc).__name__},
            ))
        db.commit()

    run = db.get(type(run), run.id)
    run.status = "completed" if failed_query_count < len(cases) or not cases else "failed"
    run.finished_at = datetime.now(UTC)

    retrieval_latencies = [item["retrieval_latency_ms"] for item in metrics]
    answer_latencies = [item["answer_latency_ms"] for item in metrics]
    run.summary_metrics_json = {
        "case_count": len(cases),
        # C07: denominators are explicit so a partially-degraded run cannot look perfect.
        "successful_query_count": sum(1 for item in metrics if item["generation_available"] == 1.0),
        "retrieval_only_query_count": sum(1 for item in metrics if item["generation_available"] == 0.0),
        "degraded_query_count": degraded_query_count,
        "failed_query_count": failed_query_count,
        "answer_coverage_denominator": len(cases),
        "recall_at_5": _average(metrics, "recall_at_5"),
        "recall_at_10": _average(metrics, "recall_at_10"),
        "mrr": _average(metrics, "reciprocal_rank"),
        "source_hit_rate": _average(metrics, "source_hit"),
        "table_hit_rate": _average(metrics, "table_hit"),
        "field_hit_rate": _average(metrics, "field_hit"),
        "citation_coverage": _average(metrics, "citation_coverage"),
        "groundedness": _average(
            [item for item in metrics if item["generation_available"] == 1.0], "groundedness"),
        # C07: answer-quality averages are over **generated** answers only; the retrieval metrics
        # above stay over every executed query (retrieval quality is still valid when generation
        # degrades, so it must not be flattened to 0).
        "answer_correctness": _average(
            [item for item in metrics if item["generation_available"] == 1.0], "answer_correctness"),
        "answer_correctness_denominator": sum(
            1 for item in metrics if item["generation_available"] == 1.0),
        "keyword_coverage": _average(metrics, "keyword_coverage"),
        "retrieval_latency_p50_ms": _percentile(retrieval_latencies, 0.50),
        "retrieval_latency_p95_ms": _percentile(retrieval_latencies, 0.95),
        "answer_latency_ms": _average(metrics, "answer_latency_ms"),
        "average_latency_ms": _average(metrics, "total_latency_ms"),
        "indexing_throughput_chunks_per_second": _indexing_throughput(active_index),
        "token_usage_total": total_token_usage,
    }
    db.commit()
    db.refresh(run)
    return run


def _retrieval_mode(value: str) -> str:
    aliases = {"formal_hybrid": "hybrid", "mock_baseline": "hybrid"}
    mode = aliases.get(str(value), str(value))
    if mode not in {"keyword_only", "vector_only", "hybrid"}:
        raise ValueError("Unsupported evaluation retrieval mode")
    return mode


# C08: bump when the digest inputs change so old and new versions stay distinguishable.
DATASET_VERSION_SCHEMA = "rag-eval-dataset-v2"


def _dataset_version(cases) -> str:
    """C08: version the dataset over the **complete** grading-relevant input.

    Previously the hash only covered ``id``, a digest of the query and the expected unit ids, so
    changing ``expected_source_system`` / ``expected_table_name`` / ``expected_field_name`` /
    ``expected_answer_keywords_json`` / ``target_field_id`` / ``scenario_id`` left the version
    unchanged -- two materially different datasets could report the same version.  Swapping two rows
    changed it, because case order leaked into the digest.

    Now every assertion the evaluator actually uses is included, the cases are ordered by a stable
    key (so an equivalent set hashes identically regardless of row order), and the schema version is
    part of the digest so future changes stay distinguishable.
    """

    ordered = sorted(cases, key=lambda case: (case.id is None, case.id))
    payload = {
        "schema": DATASET_VERSION_SCHEMA,
        "cases": [
            {
                "id": case.id,
                "query": case.query_text,
                "enabled": bool(case.enabled),
                "target_field_id": case.target_field_id,
                "scenario_id": case.scenario_id,
                "expected_knowledge_unit_ids": sorted(
                    case.expected_knowledge_unit_ids_json or []),
                "expected_source_system": case.expected_source_system,
                "expected_table_name": case.expected_table_name,
                "expected_field_name": case.expected_field_name,
                "expected_answer_keywords": sorted(
                    str(item) for item in (case.expected_answer_keywords_json or [])),
            }
            for case in ordered
        ],
    }
    material = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _indexing_throughput(index) -> float:
    if not index or not index.completed_at or not index.created_at:
        return 0.0
    created_at = index.created_at
    completed_at = index.completed_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    elapsed = max(
        0.001,
        (completed_at - created_at).total_seconds(),
    )
    return round(index.indexed_count / elapsed, 3)


def _recall(retrieved: list[int], expected: list[int]) -> float:
    return len(set(retrieved) & set(expected)) / len(expected) if expected else 1.0


def _expected_hit(text: str, expected: str | None, ranks: list[int]) -> bool:
    return expected.lower() in text if expected else bool(ranks)


def _average(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / len(items) if items else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
