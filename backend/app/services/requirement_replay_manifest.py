"""交付复核清单：把"哪些产物能用当前代码复核、哪些不能"做成可检索的一张表。

为什么需要它：

1. round 72 把 ``replay`` 三态接进了交付审计，但审计页只显示**当前筛选范围内的前几条**；
   历史产物有 35 份，要知道"到底哪些需求、哪个渲染器版本、哪张表受了影响"，只能一份份翻。
2. 客户/评审问的往往是一个具体问题——"T_1_3 那几张表的历史产物还能复核吗"——这需要按
   需求、按监管表、按渲染器版本、按关键字都能查，而不是"翻到哪算哪"。

口径（刻意保守）：

- 只读：只看产物元数据（渲染器版本、格式、来源、摘要），不读文件、不重放、不写库；
  真正的逐份重放仍然只在「稳定性核对」里做；
- 三态与交付审计同一套判定（`replay_kind` + `current_renderer_version`），避免两处口径打架；
- 「不能重放复核」不等于「不能交付」：清单只如实列"再核一遍需要当时的渲染器或模板"。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import TargetTable
from app.models.requirement import Requirement
from app.models.requirement_render import RequirementRenderArtifact
from app.services.requirement_export_stability import (
    UNSUPPORTED_REASONS,
    current_renderer_version,
    replay_kind,
)

MANIFEST_VERSION = "requirement-replay-manifest-v1"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

STATE_REPLAYABLE = "replayable"
STATE_HISTORICAL = "historical"
STATE_UNSUPPORTED = "unsupported"
STATES = (STATE_REPLAYABLE, STATE_HISTORICAL, STATE_UNSUPPORTED)

STATE_LABELS = {
    STATE_REPLAYABLE: "当前代码可复核",
    STATE_HISTORICAL: "仅旧渲染器可复核",
    STATE_UNSUPPORTED: "不支持字节重放",
}

REASON_LABELS = {
    "renderer_version_superseded": "产物登记的是旧版渲染器，当前代码再渲一遍已经不是同一份",
    **UNSUPPORTED_REASONS,
}

NOTE = (
    "复核清单只读：只列产物元数据，不读文件、不重放、不写库。"
    "「仅旧渲染器」表示这份文件用当前代码复核不出同一份，再核一遍需要当时的渲染器或模板；"
    "这不等于不能交付，也不代表查询过的产物已经核对过。"
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _scope_table_id(requirement: Requirement | None) -> int | None:
    if requirement is None:
        return None
    scope = requirement.scope_json or {}
    value = scope.get("target_table_id") if isinstance(scope, dict) else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def manifest_state(artifact: RequirementRenderArtifact) -> tuple[str, str]:
    """返回 (三态, 原因码)。判定与交付审计保持一致：先看能不能重放，再看版本对不对。"""

    kind, reason = replay_kind(artifact)
    if not kind:
        return STATE_UNSUPPORTED, reason or "renderer_unknown"
    expected = current_renderer_version(artifact)
    if expected and _text(artifact.renderer_version) != expected:
        return STATE_HISTORICAL, "renderer_version_superseded"
    return STATE_REPLAYABLE, ""


def _entry(
    artifact: RequirementRenderArtifact,
    requirement: Requirement | None,
    table: TargetTable | None,
) -> dict[str, Any]:
    state, reason = manifest_state(artifact)
    expected = current_renderer_version(artifact)
    return {
        "artifact_id": int(artifact.id),
        "requirement_id": int(artifact.requirement_id),
        "requirement_name": "" if requirement is None else _text(requirement.name),
        "target_table_code": "" if table is None else _text(table.table_code),
        "target_table_name": "" if table is None else _text(table.table_name),
        "file_name": _text(artifact.file_name),
        "format": _text(artifact.format),
        "renderer_version": _text(artifact.renderer_version),
        "current_renderer_version": expected,
        "renderer_matches_current": bool(expected) and _text(artifact.renderer_version) == expected,
        "replay_state": state,
        "replay_state_label": STATE_LABELS.get(state, state),
        "replay_reason": reason,
        "replay_reason_label": REASON_LABELS.get(reason, ""),
        "content_hash": _text(artifact.content_hash),
        "file_size": int(artifact.file_size or 0),
        "source_kind": _text(artifact.source_kind),
        "source_id": int(artifact.source_id or 0),
        "created_at": "" if artifact.created_at is None else artifact.created_at.isoformat(),
    }


def _matches(entry: dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    needle = keyword.casefold()
    haystack = " ".join(
        [
            str(entry["artifact_id"]),
            entry["file_name"],
            entry["requirement_name"],
            entry["target_table_code"],
            entry["target_table_name"],
            entry["renderer_version"],
            entry["current_renderer_version"],
        ]
    ).casefold()
    return needle in haystack


def build_replay_manifest(
    db: Session,
    project_id: int,
    *,
    state: str | None = None,
    renderer: str | None = None,
    requirement_id: int | None = None,
    keyword: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """列出项目里全部产物的复核状态，可按状态/渲染器/需求/关键字筛。"""

    if limit is not None and int(limit) < 0:
        raise ValueError("limit 不能为负数")
    limit = MAX_LIMIT if not limit else min(int(limit), MAX_LIMIT)

    state_filter = _text(state) or None
    if state_filter and state_filter not in STATES:
        raise ValueError(f"未知的复核状态：{state_filter}")
    renderer_filter = _text(renderer) or None

    artifacts = list(
        db.execute(
            select(RequirementRenderArtifact)
            .where(RequirementRenderArtifact.project_id == project_id)
            .order_by(RequirementRenderArtifact.id.desc())
        ).scalars()
    )

    requirement_ids = {int(row.requirement_id) for row in artifacts}
    requirements: dict[int, Requirement] = {}
    if requirement_ids:
        for row in db.execute(select(Requirement).where(Requirement.id.in_(requirement_ids))).scalars():
            requirements[int(row.id)] = row

    table_ids = {tid for tid in (_scope_table_id(req) for req in requirements.values()) if tid}
    tables: dict[int, TargetTable] = {}
    if table_ids:
        for row in db.execute(select(TargetTable).where(TargetTable.id.in_(table_ids))).scalars():
            tables[int(row.id)] = row

    entries = [
        _entry(
            artifact,
            requirements.get(int(artifact.requirement_id)),
            tables.get(_scope_table_id(requirements.get(int(artifact.requirement_id))) or 0),
        )
        for artifact in artifacts
    ]

    # facets 用全量算：筛选只影响返回的行，不该让"历史产物一共几份"跟着变。
    by_state: dict[str, int] = {name: 0 for name in STATES}
    by_renderer: dict[tuple[str, str], int] = {}
    by_requirement: dict[int, int] = {}
    by_table: dict[str, int] = {}
    for entry in entries:
        by_state[entry["replay_state"]] = by_state.get(entry["replay_state"], 0) + 1
        key = (entry["renderer_version"], entry["replay_state"])
        by_renderer[key] = by_renderer.get(key, 0) + 1
        by_requirement[int(entry["requirement_id"])] = by_requirement.get(int(entry["requirement_id"]), 0) + 1
        if entry["target_table_code"]:
            by_table[entry["target_table_code"]] = by_table.get(entry["target_table_code"], 0) + 1

    selected = []
    for entry in entries:
        if state_filter and entry["replay_state"] != state_filter:
            continue
        if renderer_filter and renderer_filter not in entry["renderer_version"]:
            continue
        if requirement_id is not None and int(entry["requirement_id"]) != int(requirement_id):
            continue
        if not _matches(entry, _text(keyword)):
            continue
        selected.append(entry)

    truncated = len(selected) > limit
    items = selected[:limit]

    return {
        "manifest_version": MANIFEST_VERSION,
        "project_id": int(project_id),
        "filters": {
            "state": state_filter,
            "renderer": renderer_filter,
            "requirement_id": None if requirement_id is None else int(requirement_id),
            "keyword": _text(keyword) or None,
            "limit": limit,
        },
        "summary": {
            "artifacts": len(entries),
            STATE_REPLAYABLE: by_state.get(STATE_REPLAYABLE, 0),
            STATE_HISTORICAL: by_state.get(STATE_HISTORICAL, 0),
            STATE_UNSUPPORTED: by_state.get(STATE_UNSUPPORTED, 0),
            "matched": len(selected),
            "returned": len(items),
            "truncated": truncated,
        },
        "facets": {
            "by_renderer": [
                {"renderer_version": renderer, "replay_state": state, "count": count}
                for (renderer, state), count in sorted(by_renderer.items(), key=lambda pair: (-pair[1], pair[0][0]))
            ],
            "by_requirement": [
                {
                    "requirement_id": rid,
                    "requirement_name": "" if rid not in requirements else _text(requirements[rid].name),
                    "count": count,
                }
                for rid, count in sorted(by_requirement.items(), key=lambda pair: (-pair[1], pair[0]))
            ],
            "by_table": [
                {"target_table_code": code, "count": count}
                for code, count in sorted(by_table.items(), key=lambda pair: (-pair[1], pair[0]))
            ],
        },
        "items": items,
        "state_labels": dict(STATE_LABELS),
        "note": NOTE,
    }
