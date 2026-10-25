"""可审计的输入投影账：每次生成到底用了哪些范围、丢了什么、为什么丢。

生成输入一直是"全有或全无"（超出上限直接 422），这对治理是安全的，但对**对账**不友好：
用户只看到"超限"，看不到"超了多少、卡在哪一段"。本模块只做记账，不做截断——
任何被排除的内容都必须以显式条目写明原因，禁止静默丢弃。
"""

from __future__ import annotations

import json
from typing import Any

PROJECTION_VERSION = "requirement-input-projection-v1"

KIND_PHYSICAL = "physical_source_row"
KIND_EVIDENCE = "evidence_fragment"
KIND_VERSION_PIN = "version_pin_excluded"
KIND_INPUT_BYTES = "input_bytes"


def _count(rows: Any) -> int:
    return len(rows) if rows is not None else 0


def projection_summary(
    result: dict[str, Any],
    *,
    sections: list[str] | tuple[str, ...],
    limits: dict[str, int],
    omissions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize what the frozen input actually contains.

    ``complete`` 只表示"本次投影没有因为上限被拒绝"，不表示内容业务上充分——充分性由
    缺口与审批决定，不能由这个字段替代。

    ``input_bytes`` 记录的是**不含本账本身**的负载大小：它用于和 `MAX_INPUT_BYTES`
    对齐，如果把它自身算进去会出现"记账改变被记的对象"的循环。
    """
    physical = result.get("physical_sources") or []
    evidence = result.get("evidence") or []
    fields = result.get("fields") or []
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    entries = list(omissions or [])
    return {
        "version": PROJECTION_VERSION,
        "limits": dict(limits),
        "sections": sorted(set(sections)),
        "field_count": _count(fields),
        "physical_source_count": _count(physical),
        "evidence_count": _count(evidence),
        "input_bytes": len(encoded.encode("utf-8")),
        "omissions": entries,
        "omission_count": len(entries),
        "complete": True,
    }


def version_pin_omissions(limitations: list[str]) -> list[dict[str, Any]]:
    """把版本钉扎导致的排除转成结构化条目（原因保留原文，不重新解释）。"""
    return [
        {"kind": KIND_VERSION_PIN, "reason": "version_pin", "detail": text}
        for text in limitations
    ]


def limit_exceeded_summary(
    *,
    kind: str,
    requested: int,
    limit: int,
    phase: str,
) -> dict[str, Any]:
    """超限时的可审计说明：明确"请求多少、上限多少、卡在哪一段"。"""
    return {
        "version": PROJECTION_VERSION,
        "kind": kind,
        "phase": phase,
        "requested": requested,
        "limit": limit,
        "exceeded_by": max(0, requested - limit),
        # 单位必须跟着计量口径走：输入字节预算说的是字节，物理字段预算说的才是行。
        # 之前固定写“行”，在字节超限时会报出“请求 189880 行”，误导用户按“行”去缩小范围。
        "unit": "字节" if kind == KIND_INPUT_BYTES else "行",
        "truncated": False,
        "complete": False,
        "policy": "超限不截断：必须由用户缩小资料范围后重新生成，保证候选与证据口径一致。",
    }


def limit_exceeded_message(summary: dict[str, Any], text: str) -> str:
    unit = summary.get("unit") or "行"
    return (
        f"{text}（{summary['phase']}：请求 {summary['requested']} {unit}，上限 {summary['limit']} {unit}，"
        f"超出 {summary['exceeded_by']} {unit}；不做截断）"
    )
