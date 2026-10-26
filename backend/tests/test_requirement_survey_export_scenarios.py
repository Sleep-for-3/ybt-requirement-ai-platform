"""调研表导出：场景优先分组（业务口径 6 列 + 溯源 9 列），无场景数据回退来源系统。

验收口径（replan-20261025 S3）：T_5_1 的导出要像客户示例那样**按场景**分列，
同字段多场景并列；场景行是 AI 生成的演示数据时必须带标识，且文档里写明可被人工覆盖。
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from app.services.requirement_survey_export import export_survey_document

BASE_COLUMNS = 11
BUSINESS_COLUMNS = 6
SOURCE_COLUMNS = 9


def _field(field_id: int, code: str, name: str) -> dict:
    return {
        "id": field_id,
        "field_code": code,
        "field_name": name,
        "data_category": "明细类数据",
        "data_format": "AN..60",
        "regulatory_original_definition": "监管原始口径",
        "report_field_name": name,
        "remarks": "制度包版本：R2022100101",
    }


def _scenario_row(field_id: int, scenario_id: int, **overrides) -> dict:
    row = {
        "id": field_id * 10 + scenario_id,
        "scenario_id": scenario_id,
        "target_field_id": field_id,
        "business_definition": None,
        "final_content": None,
        "ai_generated_content": None,
        "source_system_screenshot_required": False,
        "source_system_change_required": False,
        "external_data_required": False,
        "manual_supplement_required": False,
        "business_owner": None,
        "business_confirm_status": "draft",
        "confidence_level": "medium",
        "remarks": None,
        "open_questions": None,
    }
    row.update(overrides)
    return row


def _lineage_row(field_id: int, scenario_id: int, **overrides) -> dict:
    row = {
        "id": field_id * 100 + scenario_id,
        "scenario_id": scenario_id,
        "target_field_id": field_id,
        "source_system_name": None,
        "source_database_name": None,
        "source_schema_name": None,
        "source_table_english_name": None,
        "source_table_chinese_name": None,
        "source_field_english_name": None,
        "source_field_chinese_name": None,
        "processing_logic": None,
        "processing_logic_type": None,
        "tech_owner": None,
        "tech_confirm_status": "draft",
        "remarks": None,
        "ai_generated_content": None,
        "final_content": None,
        "confidence_level": "medium",
        "open_questions": None,
    }
    row.update(overrides)
    return row


def _content(with_scenarios: bool = True) -> dict:
    records = [
        {
            "field": _field(1, "E010001", "产品ID"),
            "business": {},
            "lineage": {},
            "mart_mappings": [],
        },
        {
            "field": _field(2, "E010002", "产品名称"),
            "business": {},
            "lineage": {},
            "mart_mappings": [],
        },
        {
            "field": _field(3, "E010003", "产品状态"),
            "business": {},
            "lineage": {},
            "mart_mappings": [],
        },
    ]
    content = {
        "target_table": {"table_code": "T_5_1", "table_name": "产品业务基本信息"},
        "scenario": {"scenario_name": "一表通监管报送（20261024 跑批）"},
        "requirement": {"name": "T_5_1 需求", "inclusion": None, "objective": None, "exclusion": None},
        "fields": records,
        "script_basis": {
            "rules": [
                {
                    "rule_id": "script-edge-1",
                    "target": {"table_name": "T_5_1", "column_name": "E010003"},
                    "source": {"table_name": "CPS_CARDPRODUCT", "column_name": "CARD_PRODUCT_ID"},
                    "transformation_expression": "P1.STATUS AS E010003",
                }
            ],
            "condition_texts": {},
        },
    }
    if not with_scenarios:
        return content
    content["scenario_groups"] = [
        {
            "scenario_id": 11,
            "scenario_code": "S_DEBIT",
            "scenario_name": "借记卡",
            "sort_order": 1,
            "business": [
                _scenario_row(
                    1,
                    11,
                    business_definition="借记卡产品ID按卡产品表取数",
                    final_content="借记卡产品ID取卡产品表主键",
                ),
                _scenario_row(
                    2,
                    11,
                    business_definition="借记卡产品名称取卡产品参数表名称",
                    business_owner="业务口径-借记卡负责人",
                ),
            ],
            "technical": [
                _lineage_row(
                    1,
                    11,
                    source_system_name="借记卡系统",
                    source_table_english_name="CPS_CARDPRODUCT",
                    source_table_chinese_name="申请卡种产品参数表",
                    source_field_english_name="CARD_PRODUCT_ID",
                    source_field_chinese_name="卡产品ID",
                    processing_logic="直取卡产品表主键",
                    processing_logic_type="直取",
                    tech_owner="技术口径-借记卡负责人",
                ),
                _lineage_row(
                    2,
                    11,
                    source_system_name="借记卡系统",
                    source_table_english_name="CPS_CARDPRODUCT",
                    source_table_chinese_name="申请卡种产品参数表",
                    source_field_english_name="PRODUCT_NAME",
                    source_field_chinese_name="产品名称",
                    processing_logic="直取产品名称",
                    processing_logic_type="直取",
                ),
            ],
        },
        {
            "scenario_id": 12,
            "scenario_code": "S_CREDIT",
            "scenario_name": "信用卡",
            "sort_order": 2,
            "business": [
                _scenario_row(
                    1,
                    12,
                    ai_generated_content="信用卡产品ID按贷记卡产品表取数（AI 推导）",
                )
            ],
            "technical": [
                _lineage_row(
                    1,
                    12,
                    source_system_name="贷记卡系统",
                    source_table_english_name="CC_PRODUCT",
                    source_table_chinese_name="贷记卡产品表",
                    source_field_english_name="PROD_ID",
                    source_field_chinese_name="产品ID",
                    ai_generated_content="由贷记卡产品表主键推导",
                )
            ],
        },
    ]
    return content


def _sheet(payload: bytes):
    workbook = load_workbook(BytesIO(payload))
    return workbook["需求文档"]


def _row_values(sheet, row: int) -> list:
    return [sheet.cell(row=row, column=column).value for column in range(1, sheet.max_column + 1)]


def _find_row(sheet, predicate) -> int:
    for row in range(1, sheet.max_row + 1):
        if predicate(row):
            return row
    raise AssertionError("row not found")


def test_scenario_groups_take_over_column_layout():
    sheet = _sheet(export_survey_document(_content()))
    title_row = _find_row(sheet, lambda row: sheet.cell(row=row, column=1).value == "一表通数据基础信息")
    titles = [sheet.cell(row=title_row, column=column).value for column in range(1, sheet.max_column + 1)]

    assert "业务口径-借记卡" in titles
    assert "溯源-借记卡系统" in titles
    assert "业务口径-信用卡" in titles
    assert "溯源-贷记卡系统" in titles
    # 场景没覆盖到的字段不能消失：回退到来源系统分组（本例只有脚本血缘 → 跑批脚本）
    assert "业务口径-跑批脚本" in titles

    header_row = _find_row(sheet, lambda row: sheet.cell(row=row, column=1).value == "数据项编码")
    headers = [value for value in _row_values(sheet, header_row) if value]
    assert len(headers) == BASE_COLUMNS + 3 * (BUSINESS_COLUMNS + SOURCE_COLUMNS)
    assert sheet.max_column == len(headers)


def test_scenario_values_are_written_per_group_and_ai_draft_is_marked():
    sheet = _sheet(export_survey_document(_content()))
    title_row = _find_row(sheet, lambda row: sheet.cell(row=row, column=1).value == "一表通数据基础信息")
    titles = {sheet.cell(row=title_row, column=column).value: column for column in range(1, sheet.max_column + 1)}
    debit = titles["业务口径-借记卡"]
    credit = titles["业务口径-信用卡"]
    debit_source = titles["溯源-借记卡系统"]
    credit_source = titles["溯源-贷记卡系统"]

    header_row = _find_row(sheet, lambda row: sheet.cell(row=row, column=1).value == "数据项编码")
    data_start = header_row + 1
    assert sheet.cell(row=data_start, column=1).value == "E010001"

    assert sheet.cell(row=data_start, column=debit).value == "借记卡产品ID取卡产品表主键"
    assert sheet.cell(row=data_start, column=debit_source).value == "借记卡系统"
    assert sheet.cell(row=data_start, column=debit_source + 1).value == "CPS_CARDPRODUCT"
    assert sheet.cell(row=data_start, column=debit_source + 3).value == "CARD_PRODUCT_ID"
    assert sheet.cell(row=data_start, column=debit_source + 5).value == "直取卡产品表主键"
    assert sheet.cell(row=data_start, column=debit_source + 7).value == "技术口径-借记卡负责人"

    # 信用卡组是 AI 生成草稿：必须带标识，不能看起来像已确认口径
    assert str(sheet.cell(row=data_start, column=credit).value).startswith("（AI 生成草稿，待业务确认）")
    assert str(sheet.cell(row=data_start, column=credit_source + 5).value).startswith(
        "（AI 生成草稿，待技术确认）"
    )
    assert sheet.cell(row=data_start, column=credit_source).value == "贷记卡系统"

    # 字段 2 不属于信用卡场景：该组整组留空（不是"否"，也不是占位符）
    second_row = data_start + 1
    assert sheet.cell(row=second_row, column=1).value == "E010002"
    credit_cells = [
        sheet.cell(row=second_row, column=credit + offset).value
        for offset in range(BUSINESS_COLUMNS + SOURCE_COLUMNS)
    ]
    assert all(value in (None, "") for value in credit_cells)


def test_source_notes_state_scenarios_are_demo_data():
    sheet = _sheet(export_survey_document(_content()))
    notes = [sheet.cell(row=row, column=1).value for row in range(1, sheet.max_row + 1)]
    scenario_note = next(
        value for value in notes if isinstance(value, str) and value.startswith("本表按")
    )
    assert "2 个场景" in scenario_note
    assert "借记卡" in scenario_note and "信用卡" in scenario_note
    assert "演示数据" in scenario_note
    assert "可被人工覆盖" in scenario_note
    assert any(isinstance(value, str) and value.startswith("「业务口径-借记卡」") for value in notes)


def test_completeness_reports_scenario_counts():
    sheet = _sheet(export_survey_document(_content()))
    labels = {
        sheet.cell(row=row, column=1).value: sheet.cell(row=row, column=2).value
        for row in range(1, sheet.max_row + 1)
    }
    assert labels["场景分组数"] == "2"
    assert labels["场景覆盖字段"] == "2（其余字段按来源系统分组）"


def test_structure_check_accepts_scenario_groups():
    """结构自检不能把"场景分组"判成破坏模板：v10 契约按位置配对业务口径/溯源。"""

    from app.services.requirement_survey_export import renderer_version
    from app.services.requirement_survey_structure_check import (
        check_survey_structure,
        contract_for_renderer,
    )

    version = renderer_version()
    contract = contract_for_renderer(version)
    assert contract["generation"] >= 10
    assert contract["pair_by_position"] is True

    result = check_survey_structure(export_survey_document(_content()), renderer_version=version)
    assert result["verdict"] == "pass", result["failed_keys"]
    assert result["groups"] == ["借记卡", "信用卡", "跑批脚本"]


def test_base_headers_match_customer_example():
    """11 个基础列名必须与客户示例逐字一致（含标点，不含换行）。"""

    sheet = _sheet(export_survey_document(_content()))
    header_row = _find_row(sheet, lambda row: sheet.cell(row=row, column=1).value == "数据项编码")
    headers = [sheet.cell(row=header_row, column=column).value for column in range(1, BASE_COLUMNS + 1)]
    assert headers == [
        "数据项编码",
        "数据项名称",
        "数据类别",
        "数据格式",
        "字段业务定义（监管原始口径）",
        "字段业务定义（监管定义细化）",
        "报表名称",
        "字段名称",
        "EAST口径",
        "字段业务定义（行内）",
        "备注",
    ]


def test_without_scenario_data_layout_falls_back_to_source_systems():
    sheet = _sheet(export_survey_document(_content(with_scenarios=False)))
    title_row = _find_row(sheet, lambda row: sheet.cell(row=row, column=1).value == "一表通数据基础信息")
    titles = [sheet.cell(row=title_row, column=column).value for column in range(1, sheet.max_column + 1)]
    assert "业务口径-跑批脚本" in titles
    assert "溯源-跑批脚本" in titles
    # 字段 1/2 既无集市映射也无脚本血缘 → 未登记来源；字段 3 只有脚本血缘 → 跑批脚本
    assert "业务口径-未登记来源" in titles
    assert not any(isinstance(value, str) and value.startswith("业务口径-借记卡") for value in titles)
    assert sheet.max_column == BASE_COLUMNS + 2 * (BUSINESS_COLUMNS + SOURCE_COLUMNS)
