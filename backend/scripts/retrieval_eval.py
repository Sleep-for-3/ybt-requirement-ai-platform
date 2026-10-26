r"""Offline retrieval evaluation for project 9 (read-only, in-process).

Runs the configured case set against the real ``HybridRetriever`` for several
retrieval configurations and reports Recall@5/10, MRR@10, nDCG@10, latency
percentiles and silent-degradation counts.

Golden relevance is resolved from the case's *content predicate* (a field code or
name) against the live knowledge base at evaluation time.  Cases whose predicate
matches no unit are reported separately as ``unanswerable``: they stay out of the
recall denominator so the baseline never looks better by dropping hard questions.

Usage::

    cd backend
    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe scripts\retrieval_eval.py --tag baseline_v1
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.models import KnowledgeDocument, KnowledgeUnit, Project
from app.services.retrieval.hybrid_retriever import HybridRetriever

PROJECT_ID = 9
HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "out" / "retrieval" / "cases_v1.jsonl"


@dataclass
class Config:
    name: str
    retrieval_mode: str = "hybrid"
    fusion_strategy: str = "rrf"
    vector_weight: float | None = None
    keyword_weight: float | None = None
    reranker_enabled: bool = False
    rrf_k: int | None = None
    authority_mode: str = "boost"

    def label(self, top_k: int) -> str:
        parts = [self.retrieval_mode]
        if self.retrieval_mode == "hybrid":
            parts.append(self.fusion_strategy)
            if self.fusion_strategy == "weighted":
                parts.append(f"w{self.keyword_weight}/{self.vector_weight}")
            if self.rrf_k is not None:
                parts.append(f"k{self.rrf_k}")
            if self.authority_mode != "boost":
                parts.append(self.authority_mode)
        parts.append(f"rr{int(self.reranker_enabled)}")
        parts.append(f"tk{top_k}")
        return "|".join(parts)


CONFIGS = [
    Config("keyword_only", retrieval_mode="keyword_only"),
    Config("vector_only", retrieval_mode="vector_only"),
    Config("hybrid_rrf", retrieval_mode="hybrid", fusion_strategy="rrf"),
    Config("hybrid_weighted", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.55, vector_weight=0.45),
    # M2 grid: fusion weights (keyword-heavy ... vector-heavy) and RRF k variants.
    Config("grid_w70", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.70, vector_weight=0.30),
    Config("grid_w60", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.60, vector_weight=0.40),
    Config("grid_w40", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.40, vector_weight=0.60),
    Config("grid_w30", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.30, vector_weight=0.70),
    Config("grid_rrf_k20", retrieval_mode="hybrid", fusion_strategy="rrf", rrf_k=20),
    Config("grid_rrf_k100", retrieval_mode="hybrid", fusion_strategy="rrf", rrf_k=100),
    Config("grid_rrf_rerank", retrieval_mode="hybrid", fusion_strategy="rrf", reranker_enabled=True),
    Config("grid_weighted_rerank", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.55, vector_weight=0.45, reranker_enabled=True),
    # M2 定稿候选：weighted 0.4/0.6（本轮默认值）与同权重 + cross-encoder 精排。
    Config("tuned_w40", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.4, vector_weight=0.6),
    Config("tuned_w40_rerank", retrieval_mode="hybrid", fusion_strategy="weighted", keyword_weight=0.4, vector_weight=0.6, reranker_enabled=True),
    # M2：authority 硬排序（旧行为）与加分（新行为）对照。
    Config("hybrid_rrf_strict", retrieval_mode="hybrid", fusion_strategy="rrf", authority_mode="strict"),
    Config("hybrid_rrf_boost", retrieval_mode="hybrid", fusion_strategy="rrf"),
]


CATEGORY_DOCUMENTS = {
    "regulatory": ("ybt-t51-regulatory-20261026",),
    "processing": ("ybt-t51-script-rules-20261026", "ybt-t51-lineage-20261026"),
    "lineage": ("ybt-t51-lineage-20261026",),
    "scenario": ("ybt-t51-scenarios-20261026",),
}


def resolve_golden(db, predicate: dict, category: str | None = None) -> list[int]:
    values = [str(value) for value in predicate.get("values") or [] if value]
    if not values:
        return []
    document_codes = CATEGORY_DOCUMENTS.get(category or "", ())
    if document_codes:
        scoped = _resolve_golden_units(db, values, document_codes)
        if scoped:
            return scoped
    return _resolve_golden_units(db, values, ())


def _resolve_golden_units(db, values: list[str], document_codes: tuple[str, ...]) -> list[int]:
    clauses = []
    for value in values:
        like = f"%{value}%"
        clauses.append(KnowledgeUnit.target_field_code.ilike(like))
        clauses.append(KnowledgeUnit.target_field_name.ilike(like))
        clauses.append(KnowledgeUnit.title.ilike(like))
        clauses.append(KnowledgeUnit.content.ilike(like))
    query = select(KnowledgeUnit.id).where(
        KnowledgeUnit.enabled.is_(True),
        or_(KnowledgeUnit.project_id == PROJECT_ID, KnowledgeUnit.knowledge_scope == "global"),
        or_(*clauses),
    )
    if document_codes:
        query = query.join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id).where(
            KnowledgeDocument.logical_code.in_(document_codes))
    rows = db.execute(query.order_by(KnowledgeUnit.id)).all()
    return [row[0] for row in rows]


def apply_config(settings, config: Config) -> None:
    settings.fusion_strategy = config.fusion_strategy
    settings.reranker_enabled = config.reranker_enabled
    settings.retrieval_authority_mode = config.authority_mode
    if config.rrf_k is not None:
        settings.rrf_k = config.rrf_k
    if config.keyword_weight is not None:
        settings.hybrid_keyword_weight = config.keyword_weight
    if config.vector_weight is not None:
        settings.hybrid_vector_weight = config.vector_weight


def ndcg_at(ranked: list[int], golden: set[int], k: int = 10) -> float:
    if not golden:
        return 0.0
    dcg = 0.0
    for position, unit_id in enumerate(ranked[:k], start=1):
        if unit_id in golden:
            dcg += 1.0 / math.log2(position + 1)
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(golden), k) + 1))
    return dcg / ideal if ideal else 0.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 1)


@dataclass
class RunRow:
    config: str
    top_k: int
    cases: int = 0
    answerable: int = 0
    unanswered: int = 0
    recall5: float = 0.0
    recall10: float = 0.0
    precision5: float = 0.0
    mrr10: float = 0.0
    ndcg10: float = 0.0
    degraded: int = 0
    empty: int = 0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    per_category: dict = field(default_factory=dict)
    misses: list = field(default_factory=list)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--tag", default="baseline_v1")
    parser.add_argument("--top-k", default="10,20,50")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--configs", default="")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[: args.limit]
    top_ks = [int(value) for value in args.top_k.split(",") if value.strip()]
    selected = [config for config in CONFIGS if not args.configs or config.name in args.configs.split(",")]

    settings = get_settings()
    baseline_settings = {
        "fusion_strategy": settings.fusion_strategy,
        "reranker_enabled": settings.reranker_enabled,
        "hybrid_keyword_weight": settings.hybrid_keyword_weight,
        "hybrid_vector_weight": settings.hybrid_vector_weight,
        "rrf_k": settings.rrf_k,
        "retrieval_authority_mode": settings.retrieval_authority_mode,
        "retrieval_authority_boost": settings.retrieval_authority_boost,
    }
    print(json.dumps({"cases": len(cases), "configs": [c.name for c in selected], "top_k": top_ks}, ensure_ascii=False))

    db = SessionLocal()
    rows: list[RunRow] = []
    try:
        project = db.get(Project, PROJECT_ID)
        if project is None:
            raise SystemExit(f"project {PROJECT_ID} not found")
        golden = {case["case_id"]: set(resolve_golden(db, case.get("golden") or {}, case.get("category")))
                  for case in cases}
        answerable = {case_id for case_id, ids in golden.items() if ids}
        print(json.dumps({
            "answerable_cases": len(answerable),
            "unanswerable_cases": len(cases) - len(answerable),
            "golden_units": sum(len(ids) for ids in golden.values()),
        }, ensure_ascii=False))

        retriever = HybridRetriever(db)
        for config in selected:
            apply_config(settings, config)
            for top_k in top_ks:
                print(json.dumps({"start": config.label(top_k)}, ensure_ascii=False), flush=True)
                row = RunRow(config=config.label(top_k), top_k=top_k)
                latencies: list[float] = []
                categories: dict[str, dict] = {}
                retriever.search(
                    PROJECT_ID,
                    cases[0]["query"],
                    retrieval_mode=config.retrieval_mode,
                    target_field_id=cases[0].get("target_field_id"),
                    top_k=top_k,
                    commit=False,
                )
                db.rollback()
                for case in cases:
                    case_id = case["case_id"]
                    started = time.perf_counter()
                    try:
                        log, items = retriever.search(
                            PROJECT_ID,
                            case["query"],
                            retrieval_mode=config.retrieval_mode,
                            target_field_id=case.get("target_field_id"),
                            scenario_id=case.get("scenario_id"),
                            top_k=top_k,
                            commit=False,
                        )
                    except Exception as error:  # noqa: BLE001 - recorded, not swallowed
                        db.rollback()
                        row.empty += 1
                        row.misses.append({"case_id": case_id, "error": f"{type(error).__name__}: {error}"})
                        continue
                    elapsed = (time.perf_counter() - started) * 1000.0
                    latencies.append(elapsed)
                    effective_mode = log.query_type
                    db.rollback()
                    ranked = [item["knowledge_unit_id"] for item in items]
                    row.cases += 1
                    db.expunge_all()
                    if row.cases % 20 == 0:
                        print(json.dumps({"progress": config.label(top_k), "cases": row.cases}, ensure_ascii=False), flush=True)
                    if effective_mode != config.retrieval_mode:
                        row.degraded += 1
                    if not ranked:
                        row.empty += 1
                    ids = golden.get(case_id) or set()
                    if not ids:
                        continue
                    row.answerable += 1
                    rank = next((index for index, unit_id in enumerate(ranked, start=1) if unit_id in ids), 0)
                    hit5 = 1.0 if rank and rank <= 5 else 0.0
                    hit10 = 1.0 if rank and rank <= 10 else 0.0
                    mrr = 1.0 / rank if rank and rank <= 10 else 0.0
                    ndcg = ndcg_at(ranked, ids)
                    bucket = categories.setdefault(case["category"], {"cases": 0, "hit5": 0.0, "hit10": 0.0,
                        "mrr": 0.0, "ndcg": 0.0, "precision5": 0.0})
                    bucket["cases"] += 1
                    bucket["hit5"] += hit5
                    bucket["hit10"] += hit10
                    bucket["mrr"] += mrr
                    bucket["ndcg"] += ndcg
                    precision5 = (sum(1 for unit_id in ranked[:5] if unit_id in ids) / max(1, min(5, len(ranked))))
                    row.recall5 += hit5
                    row.recall10 += hit10
                    row.precision5 += precision5
                    row.mrr10 += mrr
                    row.ndcg10 += ndcg
                    bucket["precision5"] += precision5
                    if not rank:
                        row.misses.append({
                            "case_id": case_id,
                            "category": case["category"],
                            "query": case["query"],
                            "golden": sorted(ids)[:5],
                            "top1": ranked[0] if ranked else None,
                        })
                row.unanswered = len(cases) - row.answerable
                denominator = row.answerable or 1
                row.recall5 = round(row.recall5 / denominator, 4)
                row.recall10 = round(row.recall10 / denominator, 4)
                row.precision5 = round(row.precision5 / denominator, 4)
                row.mrr10 = round(row.mrr10 / denominator, 4)
                row.ndcg10 = round(row.ndcg10 / denominator, 4)
                row.latency_p50 = percentile(latencies, 0.5)
                row.latency_p95 = percentile(latencies, 0.95)
                for category, bucket in categories.items():
                    count = bucket["cases"] or 1
                    bucket.update({
                        "recall5": round(bucket["hit5"] / count, 3),
                        "recall10": round(bucket["hit10"] / count, 3),
                        "precision5": round(bucket["precision5"] / count, 3),
                        "mrr10": round(bucket["mrr"] / count, 3),
                        "ndcg10": round(bucket["ndcg"] / count, 3),
                    })
                    for key in ("hit5", "hit10", "mrr", "ndcg", "precision5"):
                        bucket.pop(key, None)
                row.per_category = categories
                rows.append(row)
                print(json.dumps(asdict(row), ensure_ascii=False))
    finally:
        for key, value in baseline_settings.items():
            setattr(settings, key, value)
        db.close()

    out_dir = HERE / "out" / "retrieval"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "tag": args.tag,
        "project_id": PROJECT_ID,
        "cases_file": str(cases_path),
        "cases": len(cases),
        "answerable_cases": sum(1 for case_id in golden if golden[case_id]),
        "runs": [asdict(row) for row in rows],
        "settings_snapshot": {
            "retrieval_mode_default": "hybrid",
            "fusion_strategy": baseline_settings["fusion_strategy"],
            "keyword_weight": baseline_settings["hybrid_keyword_weight"],
            "vector_weight": baseline_settings["hybrid_vector_weight"],
            "reranker_enabled": baseline_settings["reranker_enabled"],
            "rrf_k": settings.rrf_k,
            "vector_top_k": settings.vector_top_k,
            "keyword_top_k": settings.keyword_top_k,
            "hybrid_final_top_k": settings.hybrid_final_top_k,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
        },
    }
    path = out_dir / f"{args.tag}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 检索评测 {args.tag}",
        "",
        f"用例 {len(cases)} 条，可回答 {payload['answerable_cases']} 条（其余为语料缺失，不计入召回分母）。",
        "",
        "| 配置 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | 降级 | 空结果 | P50 ms | P95 ms |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.config} | {row.recall5:.3f} | {row.recall10:.3f} | {row.precision5:.3f} | {row.mrr10:.3f} | {row.ndcg10:.3f} | "
            f"{row.degraded} | {row.empty} | {row.latency_p50:.1f} | {row.latency_p95:.1f} |"
        )
    lines.append("")
    lines.append("## 分类明细")
    lines.append("")
    lines.append("| 配置 | 分类 | 用例 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        for category, bucket in sorted(row.per_category.items()):
            lines.append(
                f"| {row.config} | {category} | {bucket['cases']} | {bucket['recall5']:.3f} | "
                f"{bucket['recall10']:.3f} | {bucket['mrr10']:.3f} | {bucket['ndcg10']:.3f} |"
            )
    (out_dir / f"{args.tag}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(path), "md": str(out_dir / f'{args.tag}.md')}, ensure_ascii=False))


if __name__ == "__main__":
    main()
