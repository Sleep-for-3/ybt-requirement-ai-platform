"""监管表覆盖度：项目里每一张目标监管表"有没有需求、脚本能不能产出它"。

真实问题：项目 9 有 92 张监管表、20 条需求。评审问"还差多少张表没做"时，平台只能
靠人工数（看板只列已有需求，模板页只列字段）。更糟的是有些表**脚本本身被屏蔽**
（例如 `YBT_T_3_5.sql` 整段注释），只按"有没有需求"统计会把它们算成"待办"，
实际上脚本不产出数据，做了需求也无法核对。

因此这里把三件事放在一起看：
1. 需求维：这张表是否已有需求、需求是否冻结在最近快照；
2. 脚本维：跑批脚本是否解析出了写入这张表的血缘；
3. 映射维：这张表的字段有多少已绑定监管集市映射。

判据只陈述可核实的事实，不为缺口编造原因。
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    LineageEdge,
    LineageNode,
    MartToYbtMapping,
    Requirement,
    ScriptFile,
    ScriptFileVersion,
    SqlStatement,
    StoredFile,
    TargetField,
    TargetTable,
)
from app.services.lineage.preprocessing import truncate_unterminated_block_comment
from app.services.requirement_delivery_status import build_delivery_status

COVERAGE_VERSION = "requirement-table-coverage-v1"

# 覆盖状态，按"需要动手的程度"排序：脚本产不出的表要人工确认，不该被当成待办。
COVERAGE_LABELS = {
    "frozen": "已冻结",
    "covered_draft": "有需求未冻结",
    "script_ready": "脚本可建需（未建需）",
    # 有脚本文件、但解析不出写入这张表的血缘：常见原因是脚本被整段注释屏蔽，
    # 需要人工确认"是否已停用"，不能直接当成待办去建需。
    "script_disabled": "脚本存在但未解析出写入",
    # 输入里根本没有这张表的脚本：属于资料缺口，要补脚本，而不是去调解析器。
    "script_absent": "缺少跑批脚本",
}

_STATE_ORDER = {"frozen": 0, "covered_draft": 1, "script_ready": 2, "script_disabled": 3, "script_absent": 4}

_SCRIPT_CODE = re.compile(r"YBT_(T_\d+_\d+)", re.IGNORECASE)


def _script_codes(db: Session, project_id: int) -> set[str]:
    """从脚本文件名里取监管表编号（真实脚本命名是 `YBT_T_8_1.sql`）。"""
    files = db.scalars(select(ScriptFile).where(ScriptFile.project_id == project_id)).all()
    codes: set[str] = set()
    for row in files:
        for candidate in (row.file_name, row.relative_path, row.logical_target_name):
            if not candidate:
                continue
            match = _SCRIPT_CODE.search(candidate)
            if match:
                codes.add(match.group(1).upper())
    return codes


_MAX_DIAGNOSIS_BYTES = 4 * 1024 * 1024


def disabled_reason(*, text: str | None, statement_statuses: list[str]) -> tuple[str, str] | None:
    """解释"有脚本、但没有写入血缘"的原因；只说能核实的，不猜业务。

    `text` 是脚本原文（读不到给 None）。优先判断"被块注释整段屏蔽"——这是真实数据里
    `YBT_T_3_5.sql` 的情形，和"解析失败"是两件事：前者要人工确认是否已停用，后者要看解析器。
    """
    if text:
        _, warning = truncate_unterminated_block_comment(text)
        if warning:
            return "block_comment", warning
    if not statement_statuses:
        return "no_statements", "这个脚本版本没有解析出任何语句（可能不是可解析的 SQL 脚本）"
    if all(status != "parsed" for status in statement_statuses):
        return "parse_failed", "这个脚本版本的语句都没有解析成功，需要看解析报告"
    return "no_write_target", "脚本解析成功，但没有写入这张表的血缘（可能只写临时表）"


def _version_by_code(db: Session, project_id: int) -> dict[str, ScriptFileVersion]:
    """每张监管表对应的最新脚本版本（真实命名 `YBT_T_8_1.sql`）。"""
    rows = db.execute(
        select(ScriptFileVersion, ScriptFile)
        .join(ScriptFile, ScriptFile.id == ScriptFileVersion.script_file_id)
        .where(ScriptFileVersion.project_id == project_id)
        .order_by(ScriptFileVersion.id)
    ).all()
    latest: dict[str, ScriptFileVersion] = {}
    for version, script in rows:
        for candidate in (script.file_name, script.relative_path, script.logical_target_name):
            if not candidate:
                continue
            match = _SCRIPT_CODE.search(candidate)
            if match:
                latest[match.group(1).upper()] = version
    return latest


def _version_text(db: Session, version: ScriptFileVersion) -> str | None:
    """读脚本原文用于诊断；读不到就返回 None（不因为读文件失败而丢掉覆盖度）。"""
    if not version.raw_content_storage_file_id:
        return None
    stored = db.get(StoredFile, version.raw_content_storage_file_id)
    if stored is None:
        return None
    try:
        from app.services.storage.factory import get_storage_service

        data = get_storage_service().read(stored.storage_key)
    except Exception:  # 读文件失败不影响覆盖度本身
        return None
    if len(data) > _MAX_DIAGNOSIS_BYTES:
        return None
    return data.decode("utf-8-sig", errors="replace")


def _statement_statuses(db: Session, version: ScriptFileVersion) -> list[str]:
    return list(db.scalars(
        select(SqlStatement.parse_status).where(SqlStatement.script_file_version_id == version.id)
    ).all())


def _write_targets(db: Session, project_id: int) -> dict[str, int]:
    """每张表被多少个脚本版本写入（按血缘目标节点）。"""
    rows = db.execute(
        select(LineageNode.table_name, func.count(func.distinct(LineageEdge.script_file_version_id)))
        .join(LineageEdge, LineageEdge.target_node_id == LineageNode.id)
        .where(LineageEdge.project_id == project_id)
        .group_by(LineageNode.table_name)
    ).all()
    return {name: int(count) for name, count in rows if name}


def build_table_coverage(db: Session, project_id: int) -> dict:
    """返回每张监管表的覆盖状态与汇总；只读，不写库。"""
    tables = db.scalars(
        select(TargetTable).where(TargetTable.project_id == project_id).order_by(TargetTable.table_code)
    ).all()
    field_counts = dict(db.execute(
        select(TargetField.target_table_id, func.count(TargetField.id))
        .where(TargetField.project_id == project_id)
        .group_by(TargetField.target_table_id)
    ).all())
    mapped_counts = dict(db.execute(
        select(TargetField.target_table_id, func.count(func.distinct(TargetField.id)))
        .join(MartToYbtMapping, MartToYbtMapping.target_field_id == TargetField.id)
        .where(TargetField.project_id == project_id)
        .group_by(TargetField.target_table_id)
    ).all())

    delivery = build_delivery_status(db, project_id)
    readiness_by_requirement = {item["requirement_id"]: item for item in delivery["items"]}

    requirements_by_table: dict[int, list[dict]] = defaultdict(list)
    for requirement in db.scalars(select(Requirement).where(Requirement.project_id == project_id)):
        scope = requirement.scope_json or {}
        table_id = scope.get("target_table_id")
        if not table_id:
            continue
        status = readiness_by_requirement.get(requirement.id) or {}
        requirements_by_table[int(table_id)].append({
            "requirement_id": requirement.id,
            "name": requirement.name,
            "readiness": status.get("readiness"),
            "frozen": bool(status.get("frozen")),
            "snapshot_count": status.get("snapshot_count") or 0,
            "open_gap_field_count": status.get("open_gap_field_count") or 0,
        })

    writes = _write_targets(db, project_id)
    script_codes = _script_codes(db, project_id)
    versions = _version_by_code(db, project_id)
    diagnosis_cache: dict[str, tuple[str, str] | None] = {}

    def _diagnosis(code: str) -> tuple[str, str] | None:
        if code in diagnosis_cache:
            return diagnosis_cache[code]
        version = versions.get(code.upper())
        if version is None:
            diagnosis_cache[code] = None
            return None
        result = disabled_reason(
            text=_version_text(db, version),
            statement_statuses=_statement_statuses(db, version),
        )
        diagnosis_cache[code] = result
        return result

    items: list[dict] = []
    for table in tables:
        code = table.table_code
        requirements = sorted(requirements_by_table.get(table.id, []), key=lambda row: row["requirement_id"])
        frozen = [row for row in requirements if row["frozen"]]
        script_versions = writes.get(code, 0)
        if frozen:
            state = "frozen"
        elif requirements:
            state = "covered_draft"
        elif script_versions:
            state = "script_ready"
        elif code.upper() in script_codes:
            state = "script_disabled"
        else:
            state = "script_absent"
        def _reason_for(state_name: str, table_code: str) -> tuple[str, str] | None:
            if state_name == "script_disabled":
                return _diagnosis(table_code)
            if state_name == "script_absent":
                return "script_missing", "输入资料里没有这张表的脚本（文件名未匹配 YBT_T_x_y），需要补资料"
            return None

        items.append({
            "table_id": table.id,
            "table_code": code,
            "table_name": table.table_name,
            "field_count": int(field_counts.get(table.id) or 0),
            "mapped_field_count": int(mapped_counts.get(table.id) or 0),
            "script_version_count": script_versions,
            "requirement_count": len(requirements),
            "frozen_requirement_count": len(frozen),
            "requirements": requirements,
            "state": state,
            "state_label": COVERAGE_LABELS[state],
            "script_reason_kind": reason[0] if (reason := _reason_for(state, code)) else None,
            "script_reason": reason[1] if reason else None,
        })

    items.sort(key=lambda row: (_STATE_ORDER[row["state"]], row["table_code"]))

    summary = {
        "table_count": len(items),
        "frozen": sum(1 for row in items if row["state"] == "frozen"),
        "covered_draft": sum(1 for row in items if row["state"] == "covered_draft"),
        "script_ready": sum(1 for row in items if row["state"] == "script_ready"),
        "script_disabled": sum(1 for row in items if row["state"] == "script_disabled"),
        "script_absent": sum(1 for row in items if row["state"] == "script_absent"),
        "field_count": sum(row["field_count"] for row in items),
        "mapped_field_count": sum(row["mapped_field_count"] for row in items),
    }
    return {
        "coverage_version": COVERAGE_VERSION,
        "project_id": project_id,
        "summary": summary,
        "items": items,
    }
