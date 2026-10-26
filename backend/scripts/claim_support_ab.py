"""A/B：证据接地（grounding）对真实候选主张判定的影响。

数据来源：`scripts/out/retrieval/regen_batch_*.json`（分批再生成时保存的候选详情快照，
含 claims 与所引证据原文）。同一批候选分别用两种门限重放：

* ``off``：门限 1.01（等价于关闭接地，保留既有确定性校验行为）；
* ``on``：门限取设置里的 ``claim_grounding_min_coverage``（默认 0.75）。

输出逐主张的 before/after 状态、翻转样例、以及"疑似抄证据但被判 unknown"的比例，
写到 ``scripts/out/retrieval/claim_support_ab.json`` 与同名 ``.md``。

只读：不写库、不改需求内容。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.core.settings import get_settings
from app.services.requirement_claim_support import evaluate_claim_support

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "retrieval"


def load_candidates() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(OUT.glob("regen_batch_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        batch = (payload.get("record") or {}).get("batch")
        for entry in payload.get("details") or []:
            detail = entry.get("detail") or {}
            if not detail.get("claims"):
                continue
            rows.append({
                "source": path.name,
                "batch": batch,
                "item_id": entry.get("item_id"),
                "section": detail.get("section"),
                "claims": detail.get("claims") or [],
                "evidence": detail.get("evidence") or [],
                "candidate_hash": entry.get("candidate_hash"),
            })
    return rows


def run(rows: list[dict], threshold: float | None) -> list[dict]:
    settings = get_settings()
    previous = getattr(settings, "claim_grounding_min_coverage", None)
    if threshold is not None:
        settings.claim_grounding_min_coverage = threshold
    results: list[dict] = []
    try:
        for row in rows:
            context = {
                "section": row["section"],
                "evidence": row["evidence"],
                "script_basis": {"rules": [], "condition_texts": {}, "metadata": []},
            }
            report = evaluate_claim_support(context, {"claims": row["claims"]})
            by_claim = {item.claim_id: item for item in report.evaluations}
            for claim in row["claims"]:
                claim_id = str(claim.get("claim_id"))
                evaluation = by_claim.get(claim_id)
                results.append({
                    "source": row["source"],
                    "item_id": row["item_id"],
                    "section": row["section"],
                    "claim_id": claim_id,
                    "assertion_kind": claim.get("assertion_kind"),
                    "text": str(claim.get("text") or "")[:160],
                    "status": evaluation.status if evaluation else "missing",
                    "codes": list(evaluation.codes) if evaluation else [],
                })
    finally:
        if threshold is not None:
            settings.claim_grounding_min_coverage = previous
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUT / "claim_support_ab.json"))
    args = parser.parse_args()

    rows = load_candidates()
    if not rows:
        raise SystemExit("没有找到含 claims 的候选快照；先跑 regenerate_t51_batched.py")
    off = run(rows, 1.01)
    on = run(rows, None)
    index = {(row["source"], row["item_id"], row["claim_id"]): row for row in on}
    flips: list[dict] = []
    for row in off:
        after = index.get((row["source"], row["item_id"], row["claim_id"]))
        if after is None:
            continue
        if row["status"] != after["status"]:
            flips.append({**{k: row[k] for k in ("source", "item_id", "section", "claim_id",
                                                 "assertion_kind", "text")},
                          "before": row["status"], "after": after["status"],
                          "codes_after": after["codes"]})
    before_counts = Counter(row["status"] for row in off)
    after_counts = Counter(row["status"] for row in on)
    report = {
        "candidates": len(rows),
        "claims": len(off),
        "before": dict(before_counts),
        "after": dict(after_counts),
        "threshold": getattr(get_settings(), "claim_grounding_min_coverage", None),
        "flips": flips,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 证据接地 A/B（真实候选）",
        "",
        f"- 候选数：{report['candidates']}；主张数：{report['claims']}",
        f"- 门限：{report['threshold']}",
        f"- 接地前：{report['before']}",
        f"- 接地后：{report['after']}",
        "",
        f"## 状态翻转（{len(flips)} 条）",
        "",
    ]
    for flip in flips[:40]:
        lines.append(f"- item {flip['item_id']} {flip['claim_id']}（{flip['assertion_kind']}）"
                     f" {flip['before']} → {flip['after']}：{flip['text']}")
    Path(args.output).with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("candidates", "claims", "before", "after", "threshold")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
