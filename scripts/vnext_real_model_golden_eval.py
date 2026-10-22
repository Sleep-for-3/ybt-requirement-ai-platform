"""用真实公司 DeepSeek API 跑黄金集 C 族（引用可信度）——真实模型、真实 PG 会话。

- 输入：backend/app/services/evaluation/data/vnext_golden_set_v1.json 的 C01..C10；
  每条案例的 answer / citations 严格按黄金集 scenario 转写（脚本内 CASES），
  `expected` 只能来自黄金集 `expected.citations[].reference_verdict`，不得为了让结果变好而
  修改期望值。
- 判定：走生产路径 app.services.rag.citation_validator.check_citation_support
  （CITATION_SUPPORT_CHECK=judge），模型为 backend/.env 的 openai_compatible / deepseek-v4-flash。
- C10 与 C04 额外传入 `pinned_versions`：需求快照固定的制度版本，由确定性规则判定
  版本不一致（不依赖模型“猜到”哪个版本才是交付依据）。
- 输出：每条 verdict、与期望是否一致、claim 覆盖率、冲突识别数、耗时；汇总精度。
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
        "title": "正确引用：制度条款支持字段口径",
        "answer": "贷款余额按借据余额汇总，不含已核销。",
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
        "title": "引用错误章节：引用了无关条款",
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
        "title": "引用存在但不支持结论：同义词替换过度",
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
        "title": "旧版制度冲突：新版为准",
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
        # 交付按新版：旧版引用必须由确定性版本规则判 unsupported。
        "pinned_versions": {"客户数据项说明": "2026"},
        "expected": {"c1": "unsupported", "c2": "supported"},
    },
    {
        "id": "C05",
        "title": "证据缺失：结论无任何引用",
        "answer": "取数路径为 ODS_CUSTOMER 关联 MART_CUSTOMER 后取 CUSTOMER_ID。",
        "citations": [],
        "expected": {"_none": "unknown"},
        "note": "黄金集期望 c1=unknown，但产品契约在无引用时直接返回 skip_reason=no_citations"
                "（没有任何引用可供判定）。本脚本把“无引用→未验证”视为与 unknown 等价，并单独标注。",
    },
    {
        "id": "C06",
        "title": "适用时点不同：制度生效日早于报送期",
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
        "title": "引用二手摘要而非原文",
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
        "title": "覆盖不足：多条件只引一条",
        "answer": "贷款余额口径同时满足三个条件：不含已核销、不含逾期 90 天以上、仅表内贷款。",
        "citations": [
            {
                "citation_id": "c1",
                "source_name": "一表通数据项说明",
                "location_text": "第 4.2 条",
                "quoted_content": "贷款余额不含已核销。",
            },
            {
                "citation_id": "c2",
                "source_name": "一表通数据项说明",
                "location_text": "第 4.5 条",
                "quoted_content": "逾期贷款指借款人未按合同约定日期偿还的贷款。",
            },
        ],
        "expected": {"c1": "supported", "c2": "unknown"},
        "note": "三个条件只有一条被引用直接支持：引用级 c1 supported、c2 未涉及 90 天口径 → unknown；"
                "主张级必须有 3 条原子主张、覆盖率 1/3，整体不得 verified。",
    },
    {
        "id": "C09",
        "title": "冲突资料静默合并",
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
        # 黄金集只标注了 c1=unknown（第二个来源未列入期望）；c2 必须保留在输入里，
        # 否则“冲突”根本无从暴露。c2 不参与精确匹配，但冲突识别数单独统计。
        "expected": {"c1": "unknown"},
        "note": "两份高权威来源对同一字段口径冲突：必须暴露冲突并把 c1 降级为 unknown，"
                "不得按检索顺序静默取一条。",
    },
    {
        "id": "C10",
        "title": "证据版本与快照不一致",
        "answer": "按制度 v2 口径计算贷款余额。",
        "citations": [{
            "citation_id": "c1",
            "source_name": "监管统计制度（v2）",
            "location_text": "第 4 条",
            "version": "v2",
            "quoted_content": "贷款余额按借据余额汇总，不含已核销（v2 修订口径）。",
        }],
        # 需求快照固定 v1：引用 v2 由确定性规则直接判 unsupported。
        "pinned_versions": {"监管统计制度": "v1"},
        "expected": {"c1": "unsupported"},
        "note": "版本一致性不得靠模型从版本号猜测，必须由 pinned_versions 确定性判定。",
    },
]


async def run_case(db, case: dict) -> dict:
    started = time.perf_counter()
    support = await check_citation_support(
        db,
        case["citations"],
        answer=case["answer"],
        confidentiality_levels=["internal"],
        pinned_versions=case.get("pinned_versions"),
    )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    verdicts = {str(item.get("citation_id")): item.get("verdict")
                for item in support.get("verdicts") or [] if item.get("citation_id")}
    verdict_reasons = {str(item.get("citation_id")): item.get("reason")
                       for item in support.get("verdicts") or [] if item.get("citation_id")}
    expected = case["expected"]
    base = {
        "case": case["id"],
        "title": case.get("title"),
        "expected": expected,
        "verdicts": verdicts,
        "verdict_reasons": verdict_reasons,
        "verification": support.get("verification"),
        "claim_judgement": support.get("claim_judgement"),
        "claims_total": support.get("claims_total"),
        "claims_judged": support.get("claims_judged"),
        "claims_supported": support.get("claims_supported"),
        "claims_unknown": support.get("claims_unknown"),
        "claim_coverage": support.get("claim_coverage"),
        "conflict_count": support.get("conflict_count"),
        "resolved_conflicts": support.get("resolved_conflicts"),
        "version_violations": [item.get("citation_id") for item in support.get("version_violations") or []],
        "trust_blockers": support.get("trust_blockers"),
        "latency_ms": elapsed,
        "model_name": support.get("model_name"),
        "degraded": support.get("degraded"),
        "degraded_reason": support.get("degraded_reason"),
    }
    if not case["citations"]:
        # 无引用：产品返回 skip_reason=no_citations，没有任何判定；视为“未验证”。
        matched = support.get("skip_reason") == "no_citations" and not verdicts
        base.update({
            "skip_reason": support.get("skip_reason"),
            "match_basis": "no_citations→unknown（与黄金集 c1=unknown 语义等价）",
            "matched": matched,
        })
        return base
    matched = all(verdicts.get(cid) == want for cid, want in expected.items())
    base.update({
        "missing_verdicts": [cid for cid in expected if cid not in verdicts],
        "matched": matched,
    })
    return base


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
    claim_level = sum(1 for item in results if item.get("claim_judgement") == "claim_level")
    conflicts_exposed = sum(1 for item in results if (item.get("conflict_count") or 0) > 0)
    never_verified_failures = sum(
        1 for item in results
        if not item["matched"] and item.get("verification") != "verified"
    )
    citation_verdicts = [v for item in results for v in item["verdicts"].values()]
    payload = {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "CITATION_SUPPORT_CHECK=judge, RAGAS_JUDGE_ENABLED=true, real DB session",
        "prompt": "[AI_SKILL_CITATION_SUPPORT_V2]",
        "model": next((item.get("model_name") for item in results if item.get("model_name")), None),
        "cases": total,
        "citation_verdict_exact_match": matched,
        "citation_verdict_accuracy": round(matched / total, 4) if total else None,
        "claim_level_cases": claim_level,
        "conflict_cases_exposed": conflicts_exposed,
        "failed_but_still_not_verified": never_verified_failures,
        "citation_verdict_counts": {
            verdict: citation_verdicts.count(verdict)
            for verdict in ("supported", "unsupported", "unknown")
        },
        "degraded_cases": degraded,
        "avg_latency_ms": round(sum(item["latency_ms"] for item in results) / total, 1) if total else None,
        "label_status": "UNVERIFIED",
        "label_note": "黄金集由 Lead 合成并人工转写输入，无独立银行专家标注；真实业务准确率不成立。",
        "transcription_note": "C08 补回 c2、C09 保留两份冲突证据、C10/C04 传入 pinned_versions，"
                              "期望值全部取自黄金集，未修改真值。",
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
