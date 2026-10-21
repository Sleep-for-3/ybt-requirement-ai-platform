"""用真实公司 DeepSeek API 跑黄金集 C 族（引用可信度）——真实模型、真实 PG 会话。

- 输入：backend/app/services/evaluation/data/vnext_golden_set_v1.json 的 C01..C10；
  每条案例的 answer / citations 由 Lead 依据用例 scenario 人工转写（脚本内 CASES），
  转写保持原意（正确引用、错误章节、同义词扩大、新旧版、缺证据、时点、二手摘要、
  覆盖不足、冲突合并、版本不一致），标注 reference_verdict 与黄金集一致。
- 判定：走生产路径 app.services.rag.citation_validator.check_citation_support
  （CITATION_SUPPORT_CHECK=judge），模型为 backend/.env 的 openai_compatible / deepseek-v4-flash。
- 输出：每条 verdict、与期望是否一致、耗时；汇总 supported/unsupported/unknown 精度。
- 局限：案例标签本身 UNVERIFIED（无独立银行专家标注），因此只证明「真实模型 + 真实判定路径
  在合成案例上可运行、判定方向正确」，不等于真实业务准确率。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("CITATION_SUPPORT_CHECK", "judge")
os.environ.setdefault("RAGAS_JUDGE_ENABLED", "true")

from app.core.database import SessionLocal  # noqa: E402
from app.services.rag.citation_validator import check_citation_support  # noqa: E402

CASES: list[dict] = [
    {
        "id": "C01",
        "answer": "贷款余额按借据余额汇总，不含已核销贷款。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "一表通数据项说明",
            "location_text": "第 4.2 条",
            "quoted_content": "贷款余额按借据余额汇总，不含已核销。",
        }],
        "expected": {"c1": "supported"},
    },
    {
        "id": "C02",
        "answer": "贷款余额按借据余额汇总。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "一表通数据项说明",
            "location_text": "第 5.1 条 客户基本信息报送",
            "quoted_content": "客户基本信息包括客户名称、证件类型、证件号码。",
        }],
        "expected": {"c1": "unsupported"},
    },
    {
        "id": "C03",
        "answer": "贷款余额包含全部贷款（含表外）。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "监管统计制度",
            "location_text": "第 3 条",
            "quoted_content": "表内贷款指纳入资产负债表核算的贷款。",
        }],
        "expected": {"c1": "unsupported"},
    },
    {
        "id": "C04",
        "answer": "客户统一标识取客户主键。",
        "citations": [
            {
                "citation_id": "c1",
                "source_name": "客户数据项说明（2024 旧版）",
                "location_text": "第 2.1 条",
                "version": "2024",
                "quoted_content": "客户统一标识取客户号。",
            },
            {
                "citation_id": "c2",
                "source_name": "客户数据项说明（2026 修订版）",
                "location_text": "第 2.1 条",
                "version": "2026",
                "quoted_content": "客户统一标识取客户主键 CUSTOMER_ID。",
            },
        ],
        "expected": {"c1": "unsupported", "c2": "supported"},
    },
    {
        "id": "C05",
        "answer": "取数路径为 ODS_CUSTOMER 关联 MART_CUSTOMER 后取 CUSTOMER_ID。",
        "citations": [],
        "expected": {"_none": "unknown"},
    },
    {
        "id": "C06",
        "answer": "2025 年报送期按现行制度口径计算贷款余额。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "监管统计制度（2026 版）",
            "location_text": "第 4 条",
            "effective_date": "2026-01-01",
            "quoted_content": "本制度自 2026 年 1 月 1 日起施行，贷款余额口径调整。",
        }],
        "expected": {"c1": "unsupported"},
    },
    {
        "id": "C07",
        "answer": "贷款余额不含已核销。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "监管制度培训 PPT",
            "location_text": "第 12 页",
            "quoted_content": "培训材料转述：贷款余额统计时一般会扣除已核销部分。",
        }],
        "expected": {"c1": "unknown"},
    },
    {
        "id": "C08",
        "answer": "口径同时满足三个条件：不含已核销、不含逾期 90 天以上、仅表内贷款。",
        "citations": [
            {
                "citation_id": "c1",
                "source_name": "一表通数据项说明",
                "location_text": "第 4.2 条",
                "quoted_content": "贷款余额不含已核销。",
            },
        ],
        "expected": {"c1": "supported"},
    },
    {
        "id": "C09",
        "answer": "客户统一标识取客户号。",
        "citations": [
            {
                "citation_id": "c1",
                "source_name": "客户数据项说明（A 制度）",
                "location_text": "第 2.1 条",
                "quoted_content": "客户统一标识取客户号。",
            },
            {
                "citation_id": "c2",
                "source_name": "客户数据项说明（B 制度）",
                "location_text": "第 3.2 条",
                "quoted_content": "客户统一标识取客户主键 CUSTOMER_ID。",
            },
        ],
        "expected": {"c1": "unsupported", "c2": "unsupported"},
    },
    {
        "id": "C10",
        "answer": "按制度 v2 口径计算贷款余额。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "监管统计制度",
            "location_text": "第 4 条",
            "version": "v2",
            "quoted_content": "贷款余额按借据余额汇总，不含已核销（v2 修订口径）。",
        }],
        "expected": {"c1": "unsupported"},
    },
]


async def run_case(db, case: dict) -> dict:
    started = time.perf_counter()
    support = await check_citation_support(
        db,
        case["citations"],
        answer=case["answer"],
        confidentiality_levels=["internal"],
    )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    verdicts = {str(item.get("citation_id")): item.get("verdict")
                for item in support.get("verdicts") or [] if item.get("citation_id")}
    expected = case["expected"]
    if not case["citations"]:
        matched = support.get("skip_reason") == "no_citations" or not verdicts
        return {
            "case": case["id"], "expected": expected, "verdicts": verdicts,
            "skip_reason": support.get("skip_reason"),
            "claim_judgement": support.get("claim_judgement"),
            "matched": matched, "latency_ms": elapsed,
            "model_name": support.get("model_name"),
            "degraded": support.get("degraded"),
            "degraded_reason": support.get("degraded_reason"),
        }
    matched = all(verdicts.get(cid) == want for cid, want in expected.items())
    missing = [cid for cid in expected if cid not in verdicts]
    return {
        "case": case["id"], "expected": expected, "verdicts": verdicts,
        "missing_verdicts": missing,
        "claim_judgement": support.get("claim_judgement"),
        "matched": matched, "latency_ms": elapsed,
        "model_name": support.get("model_name"),
        "degraded": support.get("degraded"),
        "degraded_reason": support.get("degraded_reason"),
        "claims_judged": support.get("claims_judged"),
        "claim_coverage": support.get("claim_coverage"),
        "supported_claims": support.get("supported_claims"),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    results = []
    with SessionLocal() as db:
        for case in CASES:
            results.append(await run_case(db, case))
    total = len(results)
    matched = sum(1 for item in results if item["matched"])
    degraded = sum(1 for item in results if item.get("degraded"))
    citation_verdicts = [v for item in results for v in item["verdicts"].values()]
    payload = {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "CITATION_SUPPORT_CHECK=judge, RAGAS_JUDGE_ENABLED=true, real DB session",
        "model": next((item.get("model_name") for item in results if item.get("model_name")), None),
        "cases": total,
        "citation_verdict_exact_match": matched,
        "citation_verdict_accuracy": round(matched / total, 4) if total else None,
        "citation_verdict_counts": {
            verdict: citation_verdicts.count(verdict)
            for verdict in ("supported", "unsupported", "unknown")
        },
        "degraded_cases": degraded,
        "avg_latency_ms": round(sum(item["latency_ms"] for item in results) / total, 1) if total else None,
        "label_status": "UNVERIFIED",
        "label_note": "黄金集由 Lead 合成并人工转写输入，无独立银行专家标注；真实业务准确率不成立。",
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
