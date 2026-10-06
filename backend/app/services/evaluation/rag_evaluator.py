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
from app.services.llm.prompt_runtime import get_prompt_runtime
from app.services.rag import grounded_answer
from app.services.semantic_index.versioning import get_active_index_version

EVALUATION_PROMPT_KEY = "regulatory_field_explanation"


class SnapshotCase:
    """R05: 从**不可变快照**还原的用例视图。

    执行与评分只读这个视图，绝不再触碰可被其他 Session 修改的 ORM 行；属性名与
    ``RagEvaluationCase`` 保持一致，因此下游评分代码无需分叉。
    """

    __slots__ = (
        "id", "query_text", "enabled", "target_field_id", "scenario_id",
        "expected_knowledge_unit_ids_json", "expected_source_system",
        "expected_table_name", "expected_field_name", "expected_answer_keywords_json",
    )

    def __init__(self, data: dict):
        self.id = data.get("id")
        self.query_text = data.get("query_text") or ""
        self.enabled = bool(data.get("enabled", True))
        self.target_field_id = data.get("target_field_id")
        self.scenario_id = data.get("scenario_id")
        self.expected_knowledge_unit_ids_json = list(data.get("expected_knowledge_units") or [])
        self.expected_source_system = data.get("expected_source_system")
        self.expected_table_name = data.get("expected_table_name")
        self.expected_field_name = data.get("expected_field_name")
        self.expected_answer_keywords_json = list(data.get("expected_answer_keywords") or [])


def build_dataset_snapshot(cases) -> dict:
    """R05: 把本次运行要用的用例**规范化并冻结**成一份自包含快照。

    快照包含评分实际使用的**全部输入与真值**，因此：
    * 运行中或运行后修改用例行，不会改变本次执行与评分所用的输入/真值；
    * 可以从快照**重算**数据集版本（不依赖任何可变的 ORM 行）；
    * API / 页面可以回看当时到底问的是什么、真值是什么。
    按 id 稳定排序，所以等价的用例集合无论行顺序如何都得到同一版本。
    """

    def sort_key(case):
        case_id = case.id if not isinstance(case, dict) else case.get("id")
        return (case_id is None, case_id)

    def read(case, attr, default=None):
        if isinstance(case, dict):
            return case.get(attr, default)
        return getattr(case, attr, default)

    ordered = sorted(cases, key=sort_key)
    return {
        "schema": DATASET_VERSION_SCHEMA,
        "cases": [
            {
                "id": read(case, "id"),
                "query_text": read(case, "query_text"),
                "enabled": bool(read(case, "enabled", True)),
                "target_field_id": read(case, "target_field_id"),
                "scenario_id": read(case, "scenario_id"),
                "expected_knowledge_units": sorted(
                    read(case, "expected_knowledge_unit_ids_json", []) or []),
                "expected_source_system": read(case, "expected_source_system"),
                "expected_table_name": read(case, "expected_table_name"),
                "expected_field_name": read(case, "expected_field_name"),
                "expected_answer_keywords": sorted(
                    str(item) for item in (read(case, "expected_answer_keywords_json", []) or [])),
            }
            for case in ordered
        ],
    }


def dataset_version_from_snapshot(snapshot: dict) -> str:
    """R05: 从已保存的快照**重算**版本（与初次运行时逐字一致）。"""

    material = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
async def run_evaluation(db, run):
    run.status = "running"
    run.started_at = datetime.now(UTC)
    db.commit()
    # R05: 先按不可变快照所需字段读一次待测用例；随后**只**从快照执行与评分。
    live_cases = list(db.scalars(
        select(RagEvaluationCase).where(
            RagEvaluationCase.project_id == run.project_id,
            RagEvaluationCase.enabled.is_(True),
        )
    ).all())
    # R05: 在**执行前**把本次要用的用例规范化并冻结成不可变快照；后续执行与评分只读它。
    snapshot = build_dataset_snapshot(live_cases)
    cases = [SnapshotCase(item) for item in snapshot["cases"]]
    config = dict(run.retrieval_config_json or {})
    retrieval_mode = _retrieval_mode(config.get("retrieval_mode", "hybrid"))
    top_k = min(max(int(config.get("top_k", 10)), 10), 50)
    active_index = get_active_index_version(db, run.project_id)
    settings = get_settings()
    # R03: 在运行开始时解析并**固定**本次真正采用的模型档案。
    # 未指定时，get_prompt_runtime 会解析到实际默认档案（最小 id 的启用项）；把它回写到
    # run.model_profile_id，于是摘要（chat_model / chat_profile_id）、逐条结果 metadata
    # 与 ModelCallLog 三者一致，不会再出现“实际跑 A、摘要写 null/环境默认”。
    # 显式指定则继续按指定执行；一旦固定，运行中修改默认配置也不会悄悄换模型。
    resolved_runtime = get_prompt_runtime(
        db, EVALUATION_PROMPT_KEY, model_profile_id=run.model_profile_id or None)
    pinned_profile_id = resolved_runtime.model_profile_id
    run.model_profile_id = pinned_profile_id
    config.update({
        "dataset_version": dataset_version_from_snapshot(snapshot),
        # R05: 保存完整快照，使 API/页面可回看且可重算版本。
        "dataset_snapshot": snapshot,
        # R03: 摘要与逐条结果使用**固定下来的**实际档案。
        "chat_provider": resolved_runtime.provider_type,
        "chat_model": resolved_runtime.model_name,
        "chat_profile_id": pinned_profile_id,
        "embedding_provider": active_index.provider if active_index else settings.embedding_provider,
        "embedding_model": active_index.model_name if active_index else settings.embedding_model or None,
        "vector_dimension": active_index.vector_dimension if active_index else settings.embedding_dimension or None,
        "index_version": active_index.id if active_index else None,
        "milvus_collection": active_index.collection_name if active_index else None,
        "retrieval_mode": retrieval_mode,
        "top_k": top_k,
        "keyword_weight": settings.hybrid_keyword_weight,
        "vector_weight": settings.hybrid_vector_weight,
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
            # R04: 回答代理与证据/引文质量必须分开计算。
            # 旧实现把“回答文本 + 引文”拼成一个 evidence_text 去算关键词覆盖，所以
            # 一个回答“请确认其他业务”（不含预期“余额”）只要引文含“余额”就拿满分。
            answer_text = str(answer["answer"] or "").lower()
            evidence_text = " ".join(
                [str(item.get("quoted_content") or "") for item in answer["citations"]]
            ).lower()
            combined_text = f"{answer_text} {evidence_text}"
            source_hit = _expected_hit(combined_text, case.expected_source_system, ranks)
            table_hit = _expected_hit(combined_text, case.expected_table_name, ranks)
            field_hit = _expected_hit(combined_text, case.expected_field_name, ranks)
            keywords = list(case.expected_answer_keywords_json or [])
            # 回答代理：**只**看回答文本。
            keyword_coverage = _keyword_coverage(keywords, answer_text)
            evidence_keyword_coverage = _keyword_coverage(keywords, evidence_text)
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
                # C07/R04: 持久化执行事实，并**保留已有的非空降级原因**。
                # 旧实现用顶层 answer.get("degraded_reason") 直接写入，会把 execution_metadata
                # 里已经有的策略拒绝/超时原因覆盖成 null。
                execution_metadata_json=_merge_execution_metadata(answer, answer_status),
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
                # R04: 证据/引文侧的关键词命中单列，不得再与回答代理混为一谈。
                "evidence_keyword_coverage": evidence_keyword_coverage,
                "answer_correctness_proxy": answer_correctness,
                "answer_status": answer_status,
                "generation_available": float(generation_available),
                "retrieval_latency_ms": retrieval_latency_ms,
                "answer_latency_ms": answer_latency_ms,
                "total_latency_ms": total_latency_ms,
            })
        except Exception as exc:
            # R04 修复：失败样本也要计入逐条状态统计（否则结果页的计数会与分母不一致）。
            failed_query_count += 1
            db.rollback()
            run = db.get(type(run), run.id)
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
    generated_metrics = [item for item in metrics if item["generation_available"] == 1.0]
    # R04: 逐条状态计数（正常/降级/异常/待确认），供结果页与分母对应。
    status_counts = {
        "grounded": sum(1 for item in metrics if item["answer_status"] == "grounded"),
        "degraded": sum(1 for item in metrics if item["answer_status"] == "degraded"),
        "needs_confirmation": sum(
            1 for item in metrics if item["answer_status"] == "needs_confirmation"),
        "error": failed_query_count,
    }
    answer_latencies = [item["answer_latency_ms"] for item in metrics]
    run.summary_metrics_json = {
        "case_count": len(cases),
        # C07: denominators are explicit so a partially-degraded run cannot look perfect.
        "successful_query_count": sum(1 for item in metrics if item["generation_available"] == 1.0),
        "retrieval_only_query_count": sum(1 for item in metrics if item["generation_available"] == 0.0),
        "degraded_query_count": degraded_query_count,
        "failed_query_count": failed_query_count,
        "answer_coverage_denominator": len(cases),
        # R04: 生成覆盖率与逐条状态计数（结果页必须显示这些，不允许只给一个无分母的 100%）。
        "generation_coverage": (
            round(len(generated_metrics) / len(cases), 4) if cases else None),
        "status_counts": status_counts,
        "actual_chat_model": run.retrieval_config_json.get("chat_model"),
        "actual_chat_profile_id": run.retrieval_config_json.get("chat_profile_id"),
        "metric_notes": {
            "retrieval_metrics": "检索质量：覆盖全部已执行查询（含降级），降级不代表检索失败",
            "groundedness": "回答代理：仅在有生成回答的样本上求均值；降级/异常样本记为不适用",
            "answer_correctness": "回答代理：关键词覆盖×0.7 + 引文覆盖×0.3，仅在生成成功样本上求均",
            "keyword_coverage": "回答代理：预期关键词在**回答文本**中的命中率（不含引文）",
            "evidence_keyword_coverage": "证据代理：预期关键词在**引文**中的命中率（单列，不作为回答正确率）",
            "not_expert_accuracy": "以上均为代理指标，不等于银行专家判定的业务正确率",
        },
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
        "keyword_coverage": _average(generated_metrics, "keyword_coverage"),
        "evidence_keyword_coverage": _average(metrics, "evidence_keyword_coverage"),
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
    """R05/C08: 数据集版本 —— 从**规范化快照**取摘要，与运行时完全同一条路径。

    因此“初次运行时写入的 dataset_version”与“事后从已保存快照重算”必定一致，
    且不依赖任何可变的 ORM 行。
    """

    return dataset_version_from_snapshot(build_dataset_snapshot(cases))


def _keyword_coverage(keywords: list[str], text: str) -> float:
    """R04: 预期关键词在**给定文本**中的命中率。

    回答代理只看回答文本，证据代理只看引文 —— 两者不再合并，
    因此“回答不含预期词、只有引文命中”不会再得到回答满分。
    """

    if not keywords:
        return 1.0
    lowered = text.lower()
    return sum(1 for item in keywords if item.lower() in lowered) / len(keywords)


def _merge_execution_metadata(answer: dict, answer_status: str) -> dict:
    """R04: 合并执行元数据时**不得用顶层缺失值覆盖已有的非空降级原因**。

    旧实现直接写 ``"degraded_reason": answer.get("degraded_reason")``，于是策略拒绝/超时
    已经写在 ``execution_metadata`` 里的原因会被覆盖成 ``null``。
    """

    metadata = dict(answer.get("execution_metadata") or {})
    metadata["answer_status"] = answer_status
    top_level_reason = answer.get("degraded_reason")
    if top_level_reason:
        metadata["degraded_reason"] = top_level_reason
    else:
        # 保留已有原因；仅当两边都为空时才是真正的“无原因”。
        metadata.setdefault("degraded_reason", None)
    return metadata


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
