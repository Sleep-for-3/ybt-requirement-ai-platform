"""一次性补丁：调研表导出支持"场景优先分组"（有场景数据按场景分列，否则回退来源系统）。"""
from pathlib import Path

TARGET = Path("app/services/requirement_survey_export.py")

NEW_FUNCS = '''
def _scenario_groups(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    """冻结内容里的场景分组（``scenario_groups``，由 document_content 读时补全）。

    没有场景行时返回空列表——调用方回退到按来源系统分组，历史文档版式不变。
    """

    groups: list[dict[str, Any]] = []
    for raw in content.get("scenario_groups") or []:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("scenario_name") or "").strip()
        if not name:
            continue
        business: dict[int, Mapping[str, Any]] = {}
        for row in raw.get("business") or []:
            field_id = row.get("target_field_id")
            if field_id is not None:
                business[int(field_id)] = row
        technical: dict[int, Mapping[str, Any]] = {}
        for row in raw.get("technical") or []:
            field_id = row.get("target_field_id")
            if field_id is not None:
                technical[int(field_id)] = row
        if not business and not technical:
            continue
        systems: list[str] = []
        for row in technical.values():
            source = str(row.get("source_system_name") or "").strip()
            if source and source not in systems:
                systems.append(source)
        groups.append(
            {
                "scenario_id": raw.get("scenario_id"),
                "scenario_name": name,
                "business": business,
                "technical": technical,
                "business_title": f"业务口径-{name}",
                "source_title": f"溯源-{'、'.join(systems) if systems else name}",
            }
        )
    return groups


def _column_plan(
    content: Mapping[str, Any],
    fields: list[Mapping[str, Any]],
    rules_by_target: Mapping[str, list[dict]],
) -> list[dict[str, Any]]:
    """列组计划：有场景数据时按场景分列，场景没覆盖到的字段回退来源系统分组。

    示例文档的分组键是"场景"（借记卡 / 信用卡 / 代销保险…），每个场景一组业务口径
    加一组溯源。场景没覆盖到的字段不能凭空消失，仍按原来的来源系统分组放在后面。
    """

    plan: list[dict[str, Any]] = []
    covered: set[int] = set()
    for group in _scenario_groups(content):
        covered.update(group["business"])
        covered.update(group["technical"])
        plan.append(
            {
                "kind": "scenario",
                "name": group["scenario_name"],
                "group": group,
                "business_title": group["business_title"],
                "source_title": group["source_title"],
            }
        )
    residual = [
        record
        for record in fields
        if int((record.get("field") or {}).get("id") or 0) not in covered
    ]
    if residual:
        for name in _groups_in_use(residual, rules_by_target):
            plan.append(
                {
                    "kind": "system",
                    "name": name,
                    "group": None,
                    "business_title": f"业务口径-{name}",
                    "source_title": f"溯源-{name}",
                }
            )
    if not plan:
        plan.append(
            {
                "kind": "system",
                "name": _UNREGISTERED_GROUP,
                "group": None,
                "business_title": f"业务口径-{_UNREGISTERED_GROUP}",
                "source_title": f"溯源-{_UNREGISTERED_GROUP}",
            }
        )
    return plan


def _scenario_business_values(row: Mapping[str, Any] | None) -> dict[str, str]:
    """场景业务口径组的取值：只用场景行里已有的事实，AI 草稿必须带标识。"""

    if not row:
        return {key: "" for key, _, _ in _BUSINESS_COLUMNS}
    definition = str(row.get("final_content") or row.get("business_definition") or "").strip()
    if not definition:
        draft = str(row.get("ai_generated_content") or "").strip()
        if draft:
            # 文档里不能出现"看起来已确认"的口径：AI 草稿一律带标识。
            definition = f"（AI 生成草稿，待业务确认）{draft}"
    return {
        "business_definition": _text(definition),
        "screenshot": "是" if row.get("source_system_screenshot_required") else "",
        "system_change": "是" if row.get("source_system_change_required") else "",
        "external_data": "是" if row.get("external_data_required") else "",
        "manual_entry": "是" if row.get("manual_supplement_required") else "",
        "business_confirmer": _text(row.get("business_owner"), ""),
    }


def _scenario_source_values(row: Mapping[str, Any] | None) -> dict[str, str]:
    """场景溯源组的取值：来源系统/表/字段/处理逻辑都照场景行写，AI 草稿带标识。"""

    if not row:
        return dict(_EMPTY_SOURCE_VALUES)
    logic = str(row.get("final_content") or row.get("processing_logic") or "").strip()
    if not logic:
        draft = str(row.get("ai_generated_content") or "").strip()
        if draft:
            logic = f"（AI 生成草稿，待技术确认）{draft}"
    return {
        "source_system": _text(row.get("source_system_name"), ""),
        "source_table_code": _text(row.get("source_table_english_name"), ""),
        "source_table_name": _text(row.get("source_table_chinese_name"), ""),
        "source_field_code": _text(row.get("source_field_english_name"), ""),
        "source_field_name": _text(row.get("source_field_chinese_name"), ""),
        "source_logic": logic,
        "source_logic_type": _text(row.get("processing_logic_type"), "") or _logic_type(logic),
        "technical_confirmer": _text(row.get("tech_owner"), ""),
        "source_remark": _text(row.get("remarks"), ""),
    }


def _scenario_notes(
    plan: list[dict[str, Any]], fields: list[Mapping[str, Any]]
) -> list[str]:
    """场景列组的说明：写清分组来源，以及这些口径是演示数据、可被人工覆盖。"""

    scenario_plan = [item for item in plan if item["kind"] == "scenario"]
    if not scenario_plan:
        return []
    total = len(fields)
    names = "、".join(item["name"] for item in scenario_plan)
    notes = [
        f"本表按 {len(scenario_plan)} 个场景分列：{names}；场景业务口径与技术溯源为演示数据"
        "（AI 生成草稿），可被人工覆盖，未经业务确认不得视为已确认。"
    ]
    for item in scenario_plan:
        group = item["group"]
        covered = len(set(group["business"]) | set(group["technical"]))
        notes.append(
            f"「{item['business_title']}」与「{item['source_title']}」覆盖 {covered}/{total} 个字段"
            f"（业务口径 {len(group['business'])} 个、技术溯源 {len(group['technical'])} 个）。"
        )
    return notes


'''


def main() -> None:
    text = TARGET.read_bytes().decode("utf-8").replace("\r\n", "\n")

    old_version = 'SURVEY_DOC_VERSION = "survey-requirement-doc-v9"'
    if old_version not in text:
        raise SystemExit("version anchor missing")
    text = text.replace(
        old_version,
        'SURVEY_DOC_VERSION = "survey-requirement-doc-v10"',
        1,
    )

    anchor = "def _completeness_rows("
    if text.count(anchor) != 1:
        raise SystemExit("insert anchor missing")
    text = text.replace(anchor, NEW_FUNCS.lstrip("\n") + anchor, 1)

    old_plan = "    groups = _groups_in_use(all_fields, rules_by_target)\n"
    if old_plan not in text:
        raise SystemExit("groups line missing")
    text = text.replace(
        old_plan,
        "    plan = _column_plan(content, all_fields, rules_by_target)\n"
        "    scenario_plan = [item for item in plan if item[\"kind\"] == \"scenario\"]\n",
        1,
    )

    old_titles = '''    column = len(_BASE_COLUMNS) + 1
    for group in groups:
        sheet.merge_cells(
            start_row=title_row,
            start_column=column,
            end_row=title_row,
            end_column=column + len(_BUSINESS_COLUMNS) - 1,
        )
        sheet.cell(
            row=title_row, column=column, value=f"业务口径-{group}"
        ).fill = _GROUP_FILL
        column += len(_BUSINESS_COLUMNS)
        sheet.merge_cells(
            start_row=title_row,
            start_column=column,
            end_row=title_row,
            end_column=column + len(_SOURCE_COLUMNS) - 1,
        )
        sheet.cell(row=title_row, column=column, value=f"溯源-{group}").fill = _GROUP_FILL
        column += len(_SOURCE_COLUMNS)
'''
    new_titles = '''    column = len(_BASE_COLUMNS) + 1
    for item in plan:
        sheet.merge_cells(
            start_row=title_row,
            start_column=column,
            end_row=title_row,
            end_column=column + len(_BUSINESS_COLUMNS) - 1,
        )
        sheet.cell(
            row=title_row, column=column, value=item["business_title"]
        ).fill = _GROUP_FILL
        column += len(_BUSINESS_COLUMNS)
        sheet.merge_cells(
            start_row=title_row,
            start_column=column,
            end_row=title_row,
            end_column=column + len(_SOURCE_COLUMNS) - 1,
        )
        sheet.cell(row=title_row, column=column, value=item["source_title"]).fill = _GROUP_FILL
        column += len(_SOURCE_COLUMNS)
'''
    if old_titles not in text:
        raise SystemExit("title block missing")
    text = text.replace(old_titles, new_titles, 1)

    old_headers = "    for _ in groups:\n"
    if old_headers not in text:
        raise SystemExit("headers loop missing")
    text = text.replace(old_headers, "    for _ in plan:\n", 1)

    old_rows = '''        mappings = record.get("mart_mappings") or []
        for group in groups:
            group_mappings = _mappings_for_group(record, group)
            # 该字段在这个来源系统里没有映射且项目里确有集市映射时整组留空：空着是
            # "没有这项来源"，写"否"或占位会把未映射说成已核实。
            # 有映射但这一组没有 → 整组留空（空着是"没有这项来源"）；
            # 整条字段都没有映射时，只给它自己的来源组填内容，别的组留空。
            field_group = None if mappings else _only_group_for(record, rules_by_target)
            if not group_mappings and (mappings or group != field_group):
                row_values.extend("" for _ in _BUSINESS_COLUMNS)
                row_values.extend("" for _ in _SOURCE_COLUMNS)
                continue
            business = _business_values(record, group, group_mappings[0] if group_mappings else None)
            source = _source_values(record, group, group_mappings, script_logic, script_sources)
            row_values.extend(business[key] for key, _, _ in _BUSINESS_COLUMNS)
            row_values.extend(source[key] for key, _, _ in _SOURCE_COLUMNS)
'''
    new_rows = '''        mappings = record.get("mart_mappings") or []
        field_id = int(field.get("id") or 0)
        for item in plan:
            if item["kind"] == "scenario":
                group = item["group"]
                business_row = group["business"].get(field_id)
                technical_row = group["technical"].get(field_id)
                # 该字段不属于这个场景（或场景里没有这一侧的事实）时整组留空：
                # 留空是"这个场景不覆盖",不是"否",也不能写占位符冒充已核实。
                if not business_row and not technical_row:
                    row_values.extend("" for _ in _BUSINESS_COLUMNS)
                    row_values.extend("" for _ in _SOURCE_COLUMNS)
                    continue
                business = _scenario_business_values(business_row)
                source = _scenario_source_values(technical_row)
                row_values.extend(business[key] for key, _, _ in _BUSINESS_COLUMNS)
                row_values.extend(source[key] for key, _, _ in _SOURCE_COLUMNS)
                continue
            group = item["name"]
            group_mappings = _mappings_for_group(record, group)
            # 该字段在这个来源系统里没有映射且项目里确有集市映射时整组留空：空着是
            # "没有这项来源"，写"否"或占位会把未映射说成已核实。
            # 有映射但这一组没有 → 整组留空（空着是"没有这项来源"）；
            # 整条字段都没有映射时，只给它自己的来源组填内容，别的组留空。
            field_group = None if mappings else _only_group_for(record, rules_by_target)
            if not group_mappings and (mappings or group != field_group):
                row_values.extend("" for _ in _BUSINESS_COLUMNS)
                row_values.extend("" for _ in _SOURCE_COLUMNS)
                continue
            business = _business_values(record, group, group_mappings[0] if group_mappings else None)
            source = _source_values(record, group, group_mappings, script_logic, script_sources)
            row_values.extend(business[key] for key, _, _ in _BUSINESS_COLUMNS)
            row_values.extend(source[key] for key, _, _ in _SOURCE_COLUMNS)
'''
    if old_rows not in text:
        raise SystemExit("data rows block missing")
    text = text.replace(old_rows, new_rows, 1)

    old_completeness = "    completeness_rows = _completeness_rows(fields, rules_by_target)\n"
    new_completeness = '''    completeness_rows = _completeness_rows(fields, rules_by_target)
    if scenario_plan:
        covered_fields: set[int] = set()
        for item in scenario_plan:
            covered_fields.update(item["group"]["business"])
            covered_fields.update(item["group"]["technical"])
        completeness_rows = completeness_rows + [
            ("场景分组数", str(len(scenario_plan))),
            ("场景覆盖字段", f"{len(covered_fields)}（其余字段按来源系统分组）"),
        ]
'''
    if old_completeness not in text:
        raise SystemExit("completeness anchor missing")
    text = text.replace(old_completeness, new_completeness, 1)

    old_notes = "    for note in _source_notes(fields, groups, rules_by_target):\n"
    new_notes = '''    system_groups = [item["name"] for item in plan if item["kind"] == "system"]
    for note in _scenario_notes(plan, fields) + _source_notes(
        fields, system_groups, rules_by_target
    ):
'''
    if old_notes not in text:
        raise SystemExit("notes anchor missing")
    text = text.replace(old_notes, new_notes, 1)

    TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print("patched", TARGET)


if __name__ == "__main__":
    main()
