"""从跑批脚本一键建需：把"脚本可建需"的监管表批量变成需求草稿。

设计边界（与手工建需同一套服务）：
- 走 `script_preview` + `create_script_requirements`，因此脚本事实、模板 sheet、字段绑定、
  制度空缺与待核验缺口都按既有规则冻结，不绕过任何治理环节；
- 只把"脚本输出列能对上监管字段"的字段纳入范围：范围里塞进脚本根本不产出的系统字段，
  生成时必然没有依据，只会制造一堆假缺口；
- 模板版本必须真的含这张监管表的 sheet，否则如实报错而不是猜一个模板。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductScenario, Requirement, ScriptFile, ScriptFileVersion, TargetField, TargetTable, TemplateVersion
from app.services.requirement_script_basis import script_preview
from app.services.requirement_script_batch import CreateScriptRequirements, ReverseTarget, create_script_requirements
from app.services.requirement_scope import ScopeInput

AUTHORING_VERSION = "requirement-script-authoring-v1"
MAX_TABLES = 10


def _latest_script_version(db: Session, project_id: int, table_code: str) -> tuple[int, str] | None:
    """按文件名 YBT_<表编号>.sql 找最近一次解析成功的脚本版本。"""
    file_name = f"YBT_{table_code}.sql"
    row = db.execute(
        select(ScriptFileVersion.id, ScriptFile.file_name)
        .join(ScriptFile, ScriptFile.id == ScriptFileVersion.script_file_id)
        .where(
            ScriptFileVersion.project_id == project_id,
            ScriptFile.project_id == project_id,
            ScriptFile.enabled.is_(True),
            ScriptFile.file_name == file_name,
            ScriptFileVersion.parse_status.in_(("parsed", "partially_parsed")),
        )
        .order_by(ScriptFileVersion.id.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def _template_version(db: Session, project_id: int) -> TemplateVersion | None:
    """优先用已激活版本；没有激活版本时退回最近一个解析出 sheet 的版本（与手工建需的约束一致：必须含该表 sheet）。"""
    active = db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.project_id == project_id, TemplateVersion.status == "active")
        .order_by(TemplateVersion.id.desc())
        .limit(1)
    )
    if active is not None:
        return active
    return db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.project_id == project_id, TemplateVersion.parse_status == "success")
        .order_by(TemplateVersion.id.desc())
        .limit(1)
    )


def _target_for(preview: dict, table_code: str) -> dict | None:
    """在预览里找这张监管表的写入目标（按表名精确匹配，忽略大小写）。"""
    wanted = table_code.upper()
    for target in preview.get("targets") or []:
        if str(target.get("table_name") or "").upper() == wanted:
            return target
    return None


def _field_bindings(preview_target: dict, fields: list[TargetField]) -> dict[str, int]:
    """脚本输出列 → 监管字段 id；只绑同名（忽略大小写）的那些列，不猜。"""
    by_code = {field.field_code.upper(): field for field in fields}
    bindings: dict[str, int] = {}
    for column in preview_target.get("columns") or []:
        field = by_code.get(str(column).upper())
        if field is not None and field.id not in bindings.values():
            bindings[str(column)] = field.id
    return bindings


def author_candidates(db: Session, project_id: int, table_codes: list[str]) -> list[dict]:
    """不写库：逐表给出"能不能一键建需"以及原因，供界面先看清再动手。"""
    template = _template_version(db, project_id)
    # 已有需求的监管表不再自动建需：SQLite 下 JSON 列不能下推 as_integer()，这里在 Python 侧归并，
    # 代价是一次很小的一次性查询，换来跨库一致。
    existing_by_table: dict[int, int] = {}
    for row in db.scalars(select(Requirement).where(Requirement.project_id == project_id)):
        table_id = (row.scope_json or {}).get("target_table_id")
        if table_id and int(table_id) not in existing_by_table:
            existing_by_table[int(table_id)] = row.id
    out: list[dict] = []
    for code in table_codes:
        table = db.scalar(select(TargetTable).where(TargetTable.project_id == project_id, TargetTable.table_code == code))
        item: dict = {"table_code": code, "table_name": table.table_name if table else None, "authorable": False}
        if table is None:
            item["reason"] = "监管表不存在"
            out.append(item)
            continue
        existing = existing_by_table.get(table.id)
        if existing is not None:
            item["reason"] = f"该监管表已有需求（#{existing}），一键建需只用于还没有需求的表"
            out.append(item)
            continue
        script = _latest_script_version(db, project_id, code)
        if script is None:
            item["reason"] = "没有找到 YBT_<表编号>.sql 的解析成功版本"
            out.append(item)
            continue
        item["script_version_id"] = script[0]
        try:
            preview = script_preview(db, project_id, [script[0]])
        except Exception as exc:  # noqa: BLE001 - 预览失败要在界面上说清原因
            item["reason"] = f"脚本预览失败：{exc}"
            out.append(item)
            continue
        target = _target_for(preview, code)
        if target is None:
            item["reason"] = "脚本没有解析出写入这张表的血缘"
            out.append(item)
            continue
        fields = list(db.scalars(select(TargetField).where(TargetField.project_id == project_id,
            TargetField.target_table_id == table.id).order_by(TargetField.id)))
        bindings = _field_bindings(target, fields)
        if not bindings:
            item["reason"] = "脚本输出列与监管字段没有同名项，无法自动绑定"
            out.append(item)
            continue
        if template is None:
            item["reason"] = "项目还没有可用的监管模板版本"
            out.append(item)
            continue
        sheets = [sheet for sheet in template.parsed_snapshot_json or []
                  if str(sheet.get("table_code") or sheet.get("sheet_name")) == code]
        if not sheets:
            item["reason"] = f"模板版本 v{template.version_no} 里没有 {code} 的 sheet"
            out.append(item)
            continue
        item.update({
            "authorable": True,
            "target_table_id": table.id,
            "template_version_id": template.id,
            "target_key": target["key"],
            "bound_field_count": len(bindings),
            "field_count": len(fields),
            "rule_count": len(preview.get("rules") or []),
            "gap_count": len(preview.get("gaps") or []),
            "preview_hash": preview["preview_hash"],
        })
        out.append(item)
    return out


def author_requirements(db: Session, project_id: int, *, table_codes: list[str], actor_id: int,
                        scenario_id: int | None = None) -> dict:
    """逐表建需；每张表独立事务，一张失败不影响其他表（失败项如实返回原因）。"""
    if not table_codes:
        raise ValueError("至少选择一张监管表")
    if len(table_codes) > MAX_TABLES:
        raise ValueError(f"一次最多为 {MAX_TABLES} 张监管表建需")
    scenario = None
    if scenario_id is not None:
        scenario = db.scalar(select(ProductScenario).where(ProductScenario.project_id == project_id,
            ProductScenario.id == scenario_id))
    if scenario is None:
        scenario = db.scalar(select(ProductScenario).where(ProductScenario.project_id == project_id)
                             .order_by(ProductScenario.id.desc()).limit(1))
    candidates = author_candidates(db, project_id, table_codes)
    items: list[dict] = []
    for candidate in candidates:
        if not candidate.get("authorable"):
            items.append({**candidate, "created": False})
            continue
        if scenario is None:
            items.append({**candidate, "created": False, "reason": "项目里还没有业务场景，无法建需"})
            continue
        fields = list(db.scalars(select(TargetField).where(TargetField.project_id == project_id,
            TargetField.target_table_id == candidate["target_table_id"]).order_by(TargetField.id)))
        preview = script_preview(db, project_id, [candidate["script_version_id"]])
        target = _target_for(preview, candidate["table_code"]) or {}
        bindings = _field_bindings(target, fields)
        payload = CreateScriptRequirements(
            script_version_ids=[candidate["script_version_id"]],
            idempotency_key=f"author-{candidate['table_code'].lower()}-{preview['preview_hash'][:12]}",
            preview_hash=preview["preview_hash"],
            targets=[ReverseTarget(
                scope=ScopeInput(
                    name=f"{candidate['table_code']} {candidate.get('table_name') or ''} 监管字段需求（脚本自动建需）".strip(),
                    target_table_id=candidate["target_table_id"],
                    field_ids=[bindings[column] for column in bindings],
                    scenario_id=scenario.id,
                ),
                template_version_id=candidate["template_version_id"],
                target_key=candidate["target_key"],
                field_bindings=bindings,
            )],
        )
        try:
            with db.begin_nested():
                result = create_script_requirements(db, project_id, payload, actor_id)
        except Exception as exc:  # noqa: BLE001 - 失败要变成可读原因，而不是让整批 500
            items.append({**candidate, "created": False, "reason": f"建需失败：{exc}"})
            continue
        requirement = (result.get("requirements") or [{}])[0]
        items.append({
            **candidate,
            "created": True,
            "deduplicated": bool(result.get("deduplicated")),
            "requirement_id": requirement.get("requirement_id"),
            "content_version": requirement.get("content_version"),
            "bound_field_count": len(bindings),
        })
    db.flush()
    return {
        "authoring_version": AUTHORING_VERSION,
        "scenario_id": scenario.id if scenario else None,
        "item_count": len(items),
        "created_count": sum(1 for item in items if item.get("created")),
        "items": items,
    }
