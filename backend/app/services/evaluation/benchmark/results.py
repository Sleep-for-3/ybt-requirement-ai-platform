"""Assemble ``results.json`` for the overnight handoff.

The record deliberately keeps the four evidence classes apart, because the task book forbids
collapsing them:

1. **静态确认** -- code facts read from the tree (settings defaults, family coverage);
2. **确定性 / Mock 已验证** -- the benchmark run and the targeted test suites;
3. **真实组件已验证** -- runs that touched a real component (PostgreSQL/Redis/Celery) or a
   real service entry point over a real catalog;
4. **真实模型效果已验证** -- empty this round: no paid external model call was made.

Every metric carries its own denominator.  A missing number is ``null`` with a reason, never a
zero that would read as "perfect".

Usage:
    python -m app.services.evaluation.benchmark.results \
        --before ../../_runs/benchmark-before.json \
        --after ../../_runs/benchmark-after.json \
        --full-regression ../../_runs/full-regression.json \
        --out ../../docs/handoff/overnight-20261019/results.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.services.evaluation.benchmark import dataset
from app.services.evaluation.benchmark.cases import load_cases
from app.services.evaluation.benchmark.compare import compare, harness_digest


def _git(*args: str) -> str:
    try:
        completed = subprocess.run(("git", *args), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _settings_facts() -> dict:
    """Read the shipped defaults so a report cannot claim a switch was flipped when it was not."""
    from app.core.settings import get_settings

    settings = get_settings()
    return {
        "citation_support_check_default": settings.citation_support_check,
        "ragas_judge_enabled_default": settings.ragas_judge_enabled,
        "field_rerank_timeout_seconds_default": settings.field_rerank_timeout_seconds,
        "reranker_enabled_default": settings.reranker_enabled,
        "llm_provider": settings.llm_provider,
        "vector_store_provider": settings.vector_store_provider,
        "auth_mode": settings.auth_mode,
        "task_queue_provider": settings.task_queue_provider,
        "note": "以上为当前生效值；benchmark 在进程内单独切换到 judge 路径，不改默认配置",
    }


def _rerank_facts(before: dict, after: dict) -> dict:
    """The four rerank facts side by side, taken from the recorded runs rather than asserted."""
    def pick(record: dict, case_id: str) -> dict:
        for case in record.get("cases") or []:
            if case.get("case_id") == case_id:
                return case.get("observed") or {}
        return {}

    rows = {}
    for case_id in ("C4-A1", "C4-B1", "C4-C1"):
        rows[case_id] = {
            "before": {k: pick(before, case_id).get(k) for k in
                       ("recalled", "admitted", "model_evaluated", "returned",
                        "tail_ranks_not_model_evaluated", "planner")},
            "after": {k: pick(after, case_id).get(k) for k in
                      ("recalled", "admitted", "model_evaluated", "returned",
                       "tail_ranks_not_model_evaluated", "planner", "batch_count",
                       "coverage_label", "coverage_mismatch")},
        }
    return rows


def _citation_facts(after: dict) -> dict:
    """Judgement coverage for the three cases that exposed the unanswered-evidence problem."""
    rows = {}
    for case in after.get("cases") or []:
        if case.get("case_id") in {"C1-H2", "C3-A2", "C5-A2", "C1-A1", "C2-F1", "C2-G1"}:
            observed = case.get("observed") or {}
            rows[case["case_id"]] = {
                "verdict": case.get("verdict"),
                "answer_status": observed.get("answer_status"),
                "supported": observed.get("supported"),
                "unsupported": observed.get("unsupported"),
                "unknown": observed.get("unknown"),
                "judged_count": observed.get("judged_count"),
                "degraded": observed.get("degraded"),
                "failures": case.get("failures"),
            }
    return rows


def build(
    *,
    before_path: str,
    after_path: str,
    full_regression: str = "",
    targeted: list[dict] | None = None,
) -> dict:
    before = json.loads(Path(before_path).read_text(encoding="utf-8")) if before_path else {}
    after = json.loads(Path(after_path).read_text(encoding="utf-8")) if after_path else {}
    corpus = sorted(load_cases(), key=lambda case: case["case_id"])
    coverage = dataset.coverage(corpus)
    splits = dataset.split_cases(corpus)

    payload: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "code": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_dirty": bool(_git("status", "--porcelain")),
            "baseline_head": before.get("code_head"),
            "baseline_worktree": "..\\_baseline-353420d (detached worktree, same SHA)",
        },
        "dataset": {
            "schema": dataset.DATASET_SCHEMA,
            "digest": dataset.content_hash(corpus),
            "harness_digest": harness_digest(),
            "case_count": coverage["total"],
            "by_family": coverage["by_family"],
            "families_complete": coverage["families_complete"],
            "seed_group_count": len({case["seed_id"] for case in corpus}),
            "split_sizes": {name: len(cases) for name, cases in splits.items()},
            "split_digests": {name: dataset.content_hash(sorted(cases, key=lambda c: c["case_id"]))
                              for name, cases in splits.items()},
            "provenance": "全部为合成案例（synthetic=True, provenance=synthetic*），不含业务数据",
        },
        # ---------------------------------------------------------------- four evidence classes
        "evidence_classes": {
            "static_confirmed": {
                "description": "从代码与配置读出的静态事实，未运行任何被测路径",
                "settings_defaults": _settings_facts(),
                "families_declared": list(dataset.FAMILIES),
                "families_executable": list(dataset.EXECUTABLE_FAMILIES),
            },
            "deterministic_or_mock_verified": {
                "description": "跑通真实服务入口，仅把模型边界替换为确定性桩；"
                               "证明协议、状态机与预算机制，不证明真实模型效果",
                "benchmark_before": before.get("aggregate"),
                "benchmark_after": after.get("aggregate"),
                "comparison": compare(before, after) if before and after else None,
                "targeted_suites": targeted or [],
                "rerank_four_facts": _rerank_facts(before, after) if before and after else {},
                "citation_judgement_coverage": _citation_facts(after) if after else {},
            },
            "real_component_verified": {
                "description": "触及真实组件的验证结果",
                "full_backend_regression": (
                    json.loads(Path(full_regression).read_text(encoding="utf-8"))
                    if full_regression and Path(full_regression).exists() else None),
                "real_catalog_via_orm": "rerank 家族在真实 SQLite catalog 上跑通 recall + "
                                        "envelope + measure_batch_capacity + rerank_fields，"
                                        "并真实复核 resolve_skill 的内容哈希/依赖哈希/作用域",
                "postgres_redis_celery": "本机 5432/6379 监听中，但本轮未对队列/持久化做真实组件验证",
            },
            "real_model_effect_verified": {
                "description": "真实模型效果",
                "verified": False,
                "call_count": 0,
                "why": "本轮未获新增付费模型评测预算授权；全部模型调用由确定性桩替代。"
                       "真实 Top1/Top3 提升、引用支撑的真实判定质量均保持未验证。",
            },
        },
        "budget": {
            "planning_hours": 8,
            "real_model_calls": 0,
            "benchmark_gateway_calls_before": (before.get("aggregate") or {}).get("gateway_calls_total"),
            "benchmark_gateway_calls_after": (after.get("aggregate") or {}).get("gateway_calls_total"),
            "note": "harness 自身 token 与平台测试 token 分开统计，两者均未计入真实模型费用",
        },
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--full-regression", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    payload = build(before_path=args.before, after_path=args.after,
                    full_regression=args.full_regression)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
