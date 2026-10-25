"""脚本版本差异：冻结的脚本依据与同一脚本最新版本，在目标字段层面差在哪。

为什么单独做：新鲜度只回答"依据落后了"，不回答"落后多少、影响了哪些字段"。
评审看到「脚本有更新」之后必须能判断这次更新是否真的触及本条需求所绑定的字段。
这里只比较目标字段（表名.列名）及其上的加工事实，不重算哈希、不改任何需求。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LineageEdge, LineageNode, ScriptFile, ScriptFileVersion, TargetField

DIFF_VERSION = "requirement-script-basis-diff-v1"
MAX_ENTRIES = 50
MAX_SNIPPET = 240

DIFF_FIELDS = (
    "transformation_expression",
    "join_condition",
    "filter_condition",
    "aggregation_rule",
    "code_mapping_rule",
)
FIELD_LABELS = {
    "transformation_expression": "取值表达式",
    "join_condition": "关联条件",
    "filter_condition": "过滤条件",
    "aggregation_rule": "聚合规则",
    "code_mapping_rule": "码值映射",
}

# 取值表达式变了意味着"这个字段是什么"变了；条件类变化改变的是"取哪些行"。
# 前者只能重新生成候选并人工采纳（正文不会自己跟着变），后者可以先复核口径再重新冻结对齐。
EXPRESSION_FIELDS = ("transformation_expression",)
CONDITION_FIELDS = ("join_condition", "filter_condition", "aggregation_rule", "code_mapping_rule")
IMPACT_RECOMMENDATIONS = ("no_action", "review_and_rebase", "regenerate")
IMPACT_LABELS = {
    "no_action": "无需动作",
    "review_and_rebase": "复核口径后重新冻结",
    "regenerate": "重新生成候选并人工采纳",
}


def bound_field_codes(db: Session, project_id: int, field_bindings: Any) -> set[str]:
    """把需求冻结的字段绑定换算成监管字段代码集合。

    绑定表的值是目标字段 id（键是脚本输出列名），差异表用的却是目标列代码——
    两边不换算就会把"这个字段被改到了"判成"没改"。
    """
    ids: set[int] = set()
    if isinstance(field_bindings, Mapping):
        for value in field_bindings.values():
            if isinstance(value, int) and not isinstance(value, bool):
                ids.add(value)
    if not ids:
        return set()
    rows = db.scalars(
        select(TargetField.field_code).where(
            TargetField.project_id == project_id,
            TargetField.id.in_(sorted(ids)),
        )
    )
    return {str(code) for code in rows if code}


def _impact(diff: Mapping[str, Any], bound_codes: set[str]) -> dict[str, Any]:
    """把"改了哪些目标字段"换算成"这条需求该做什么"。"""
    wanted = {code.upper() for code in bound_codes}
    changed = [entry for entry in diff.get("changed") or [] if isinstance(entry, Mapping)]
    affected = [entry for entry in changed if str(entry.get("column_name") or "").upper() in wanted]
    expression = [entry for entry in affected if set(entry.get("field_keys") or ()) & set(EXPRESSION_FIELDS)]
    condition = [entry for entry in affected if set(entry.get("field_keys") or ()) & set(CONDITION_FIELDS)]
    if diff.get("state") == "aligned":
        recommendation = "no_action"
        reason = "脚本依据就是最新版本，无需动作"
    elif diff.get("state") == "version_missing":
        recommendation = "no_action"
        reason = "冻结的脚本版本已不存在：请先确认脚本去向，再决定是否重建需求"
    elif not affected:
        recommendation = "no_action"
        reason = f"这次脚本更新没有触及本需求绑定的 {len(bound_codes)} 个字段"
    elif expression:
        recommendation = "regenerate"
        reason = (
            f"{len(expression)} 个绑定字段的取值表达式变了：字段口径需要重新生成候选并人工采纳，"
            "只重新冻结不会更新正文"
        )
    else:
        recommendation = "review_and_rebase"
        reason = f"{len(condition)} 个绑定字段的取数条件变了：先按字段复核影响口径，再重新冻结对齐"
    return {
        "bound_field_count": len(bound_codes),
        "affected_field_count": len(affected),
        "affected_fields": [
            {
                "table_name": entry.get("table_name"),
                "column_name": entry.get("column_name"),
                "label": entry.get("label"),
                "field_keys": list(entry.get("field_keys") or ()),
                "field_labels": [FIELD_LABELS.get(name, name) for name in (entry.get("field_keys") or ())],
            }
            for entry in affected[:20]
        ],
        "expression_field_count": len(expression),
        "condition_field_count": len(condition),
        "recommendation": recommendation,
        "recommendation_label": IMPACT_LABELS[recommendation],
        "reason": reason,
    }


def _snippet(values: set[str]) -> str | None:
    """取可读样本：最多并列两条，其余只标条数。

    并列两条是刻意的：真实脚本里同一个目标字段常有多条过滤条件，
    只给排序第一条会把"新加的那条"藏起来，看差异的人以为没变。
    """
    if not values:
        return None
    ordered = sorted(values)
    shown = []
    for text in ordered[:2]:
        text = text.strip()
        if len(text) > MAX_SNIPPET:
            text = text[:MAX_SNIPPET] + "…"
        shown.append(text)
    snippet = "；".join(shown)
    if len(ordered) > 2:
        snippet = f"{snippet}（另有 {len(ordered) - 2} 条）"
    return snippet


def collect_signatures(db: Session, project_id: int, version_id: int) -> dict[tuple[str, str], dict[str, set[str]]]:
    """目标字段 → 五个加工事实的文本集合。"""
    columns = [getattr(LineageEdge, name) for name in DIFF_FIELDS]
    rows = db.execute(
        select(LineageNode.table_name, LineageNode.column_name, *columns)
        .join(LineageNode, LineageEdge.target_node_id == LineageNode.id)
        .where(
            LineageEdge.project_id == project_id,
            LineageEdge.script_file_version_id == version_id,
            LineageEdge.enabled.is_(True),
        )
    )
    signatures: dict[tuple[str, str], dict[str, set[str]]] = {}
    for row in rows:
        table_name, column_name = row[0], row[1]
        if not table_name or not column_name:
            continue
        bucket = signatures.setdefault((table_name, column_name), {name: set() for name in DIFF_FIELDS})
        for name, value in zip(DIFF_FIELDS, row[2:]):
            text = (value or "").strip()
            if text:
                bucket[name].add(text)
    return signatures


def diff_signatures(
    frozen: dict[tuple[str, str], dict[str, set[str]]],
    latest: dict[tuple[str, str], dict[str, set[str]]],
    *,
    max_entries: int = MAX_ENTRIES,
) -> dict[str, Any]:
    """纯函数：两组签名的目标字段级差异。"""
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for key in sorted(set(frozen) | set(latest)):
        table_name, column_name = key
        label = f"{table_name}.{column_name}"
        if key not in frozen:
            added.append(
                {
                    "table_name": table_name,
                    "column_name": column_name,
                    "label": label,
                    "after": {
                        FIELD_LABELS[name]: _snippet(latest[key][name]) for name in DIFF_FIELDS if latest[key][name]
                    },
                }
            )
            continue
        if key not in latest:
            removed.append({"table_name": table_name, "column_name": column_name, "label": label})
            continue
        changed_fields = [name for name in DIFF_FIELDS if frozen[key][name] != latest[key][name]]
        if not changed_fields:
            continue
        changed.append(
            {
                "table_name": table_name,
                "column_name": column_name,
                "label": label,
                "fields": [FIELD_LABELS[name] for name in changed_fields],
                "field_keys": changed_fields,
                "before": {FIELD_LABELS[name]: _snippet(frozen[key][name]) for name in changed_fields},
                "after": {FIELD_LABELS[name]: _snippet(latest[key][name]) for name in changed_fields},
            }
        )

    shared = set(frozen) & set(latest)
    unchanged = len(shared) - len(changed)
    # 截断只截展示，计数永远保留真实值——否则会让人以为只差这么多。
    return {
        "diff_version": DIFF_VERSION,
        "frozen_field_count": len(frozen),
        "latest_field_count": len(latest),
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "unchanged_count": unchanged,
        "added": added[:max_entries],
        "removed": removed[:max_entries],
        "changed": changed[:max_entries],
        "truncated": len(added) > max_entries or len(removed) > max_entries or len(changed) > max_entries,
        "max_entries": max_entries,
    }


def _latest_version(db: Session, project_id: int, script_file_id: int) -> ScriptFileVersion | None:
    return db.scalar(
        select(ScriptFileVersion)
        .where(
            ScriptFileVersion.project_id == project_id,
            ScriptFileVersion.script_file_id == script_file_id,
        )
        .order_by(ScriptFileVersion.version_no.desc())
        .limit(1)
    )


def build_script_basis_diff(
    db: Session,
    project_id: int,
    *,
    versions: Iterable[dict[str, Any]],
    bound_codes: set[str] | None = None,
    max_entries: int = MAX_ENTRIES,
) -> dict[str, Any]:
    """对一条需求冻结的每个脚本版本，给出与同脚本最新版本的字段级差异。

    只对"同一脚本文件"比较：换了脚本文件（改名/重新建文件）不是版本推进，照它比较会得出错误的"新增/删除"。

    `bound_codes` 是本需求绑定字段的监管字段代码；给了才会算 `impact`（要不要重新冻结、还是必须重新生成候选）。
    """
    items: list[dict[str, Any]] = []
    for version in versions:
        if not isinstance(version, dict):
            continue
        frozen_version_id = version.get("id")
        script_file_id = version.get("script_file_id")
        if not isinstance(frozen_version_id, int) or not isinstance(script_file_id, int):
            continue
        frozen = db.get(ScriptFileVersion, frozen_version_id)
        if frozen is None:
            items.append(
                {
                    "script_file_id": script_file_id,
                    "file_name": version.get("path"),
                    "state": "version_missing",
                    "frozen_version_id": frozen_version_id,
                    "latest_version_id": None,
                    "impact": _impact({"state": "version_missing"}, bound_codes or set()),
                }
            )
            continue
        latest = _latest_version(db, project_id, script_file_id)
        script_file = db.get(ScriptFile, script_file_id)
        file_name = getattr(script_file, "file_name", None) or version.get("path")
        if latest is None or latest.id == frozen.id:
            items.append(
                {
                    "script_file_id": script_file_id,
                    "file_name": file_name,
                    "state": "aligned",
                    "frozen_version_id": frozen.id,
                    "frozen_version_no": frozen.version_no,
                    "latest_version_id": latest.id if latest else None,
                    "latest_version_no": latest.version_no if latest else None,
                    "impact": _impact({"state": "aligned"}, bound_codes or set()),
                }
            )
            continue
        body = diff_signatures(
            collect_signatures(db, project_id, frozen.id),
            collect_signatures(db, project_id, latest.id),
            max_entries=max_entries,
        )
        items.append(
            {
                "script_file_id": script_file_id,
                "file_name": file_name,
                "state": "advanced",
                "frozen_version_id": frozen.id,
                "frozen_version_no": frozen.version_no,
                "latest_version_id": latest.id,
                "latest_version_no": latest.version_no,
                **body,
                "impact": _impact({"state": "advanced", **body}, bound_codes or set()),
            }
        )
    return {"diff_version": DIFF_VERSION, "item_count": len(items), "items": items}
