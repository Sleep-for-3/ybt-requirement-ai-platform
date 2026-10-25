"""P1-D 长知识单元检索分片：可复现的信号保留证据（不宣称召回提升）。

用法（在 ai-platform/backend 下，需 PYTHONPATH=.）：
    python ../scripts/requirement_chunking_report.py --output ../docs/requirement-delivery-upgrade/evidence/p1d-chunking-report.json

本脚本只回答两个可判定问题：
1. 一条超长知识单元在"截断到 480 token"时，头部/中部/尾部信号分别还剩几个；
2. 用 `plan_fragments` 分片后，三个信号是否各自落在不同片段里，且片段拼接与原文逐字符相同。

它**不是**召回评测：没有真实 embedding、没有向量库、没有 TopK/MRR。真实召回指标须在真实
embedding 与真实索引上测量，本仓库当前环境不具备，故一律不外推。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.services.semantic_index.chunking import (
    DEFAULT_MAX_TOKENS,
    FRAGMENT_STRATEGY_VERSION,
    audit_units,
    estimate_tokens,
    plan_fragments,
    resolve_fragment_hit,
)

HEAD_SIGNAL = "头部信号：只报送正常贷款余额"
MIDDLE_SIGNAL = "中部信号：复合键为(客户号, 机构号)"
TAIL_SIGNAL = "尾部信号：统计时点取上一自然月末"


def build_long_unit(*, filler_rows: int = 60) -> SimpleNamespace:
    """构造一条远超单次 embedding 预算的知识单元，信号分别放在头/中/尾。"""

    rows = [f"{HEAD_SIGNAL}"]
    for index in range(filler_rows):
        rows.append(f"字段口径{index:03d}：按机构维度汇总，空值不参与计算，码值转换为国标。")
    rows.append(f"{MIDDLE_SIGNAL}")
    for index in range(filler_rows):
        rows.append(f"关联说明{index:03d}：以客户号关联客户主表，同一机构号下唯一。")
    rows.append(f"{TAIL_SIGNAL}")
    content = "\n".join(rows)
    return SimpleNamespace(
        id=9001,
        document_id=501,
        document_version_id=77,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        confidentiality_level="internal",
        project_id=7,
        knowledge_scope="project",
        institution_name=None,
        knowledge_type="field_mapping",
        target_field_code=None,
        scenario_id=None,
        source_sheet_name="指标",
        source_cell_range="A1:D200",
        source_page_no=None,
        source_heading=None,
    )


def truncate_to_budget(text: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """模拟"只取前 N token"的旧做法，用于对照信号丢失。"""

    if estimate_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = parser.parse_args()

    unit = build_long_unit()
    content = unit.content
    fragments = plan_fragments(unit, max_tokens=args.max_tokens)
    truncated = truncate_to_budget(content, args.max_tokens)

    signals = {"head": HEAD_SIGNAL, "middle": MIDDLE_SIGNAL, "tail": TAIL_SIGNAL}
    baseline = {name: truncated.count(text) for name, text in signals.items()}
    fragment_placement: dict[str, list[int]] = {}
    for name, text in signals.items():
        places = [fragment.fragment_index for fragment in fragments if text in fragment.text]
        fragment_placement[name] = places
    reconstructed = "".join(fragment.text for fragment in fragments)
    hit = resolve_fragment_hit(
        {
            "knowledge_unit_id": unit.id,
            "parent_unit_id": unit.id,
            "citation_id": f"knowledge-unit-{unit.id}",
            "fragment_index": 2,
            "fragment_char_start": fragments[2].char_start if len(fragments) > 2 else 0,
            "fragment_char_end": fragments[2].char_end if len(fragments) > 2 else 0,
        }
    )

    report = {
        "kind": "p1d-chunking-signal-evidence",
        "not_recall_measurement": True,
        "statement": (
            "本报告只验证分片规划是否保留原文信号与坐标，不构成召回率、TopK 或 MRR 结论；"
            "真实召回须在真实 embedding 与真实向量库上测量，当前环境不具备。"
        ),
        "fragment_strategy_version": FRAGMENT_STRATEGY_VERSION,
        "max_tokens": args.max_tokens,
        "counter": "estimate-tokens-v1（CJK 1 字符≈1 token、ASCII 4 字符≈1 token，非真实 tokenizer）",
        "unit": {
            "content_chars": len(content),
            "estimated_tokens": estimate_tokens(content),
            "content_sha256": unit.content_hash,
        },
        "fragments": {
            "count": len(fragments),
            "sizes_chars": [len(fragment.text) for fragment in fragments],
            "max_estimated_tokens": max((fragment.estimated_tokens for fragment in fragments), default=0),
            "all_within_budget": all(fragment.estimated_tokens <= args.max_tokens for fragment in fragments),
            "non_overlapping": all(
                fragments[index].char_end <= fragments[index + 1].char_start
                for index in range(len(fragments) - 1)
            ),
            "reconstruction_equals_source": reconstructed == content,
        },
        "baseline_truncation": {
            "kept_chars": len(truncated),
            "signal_occurrences": baseline,
            "lost_signals": [name for name, count in baseline.items() if count == 0],
        },
        "fragment_signals": {
            "placement": fragment_placement,
            "each_signal_present_once": all(len(places) >= 1 for places in fragment_placement.values()),
            "signals_in_distinct_fragments": len(
                {place for places in fragment_placement.values() for place in places}
            ) == len(fragment_placement),
        },
        "citation_resolution": hit,
        "audit": audit_units([unit], max_tokens=args.max_tokens),
        "verdict": (
            "FRAGMENT_PLANNING_PRESERVES_SIGNALS（隔离测试：信号保留与坐标可复原）"
            if all(len(places) >= 1 for places in fragment_placement.values()) and reconstructed == content
            else "FRAGMENT_PLANNING_LOSES_SIGNALS"
        ),
        "business_or_recall_verified": False,
        "unverified": [
            "真实 tokenizer 下的片段长度（当前用估算计数器）",
            "真实 embedding 与向量库下的检索命中率、TopK、MRR",
            "接入 reindex 后的索引切换与回滚（本轮未接线）",
        ],
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
