"""一表通调研表式导出的结构自检：通过/失败都必须是可判定的结论。"""

from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.services.requirement_survey_export import export_survey_document
from app.services.requirement_survey_structure_check import (
    STRUCTURE_CHECK_VERSION,
    STRUCTURE_CONTRACT_VERSION,
    StructureCheckError,
    check_survey_structure,
    contract_for_renderer,
)
from test_requirement_survey_export import _content


def _mutate(payload: bytes, mutate) -> bytes:
    workbook = load_workbook(BytesIO(payload))
    sheet = workbook["需求文档"]
    mutate(sheet)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_real_export_passes_structure_check():
    result = check_survey_structure(export_survey_document(_content()))
    assert result["check_version"] == STRUCTURE_CHECK_VERSION
    assert result["verdict"] == "pass"
    assert result["failed_keys"] == []
    assert result["field_rows"] == 1
    assert result["groups"] == ["监管集市"]
    checks = {item["key"]: item for item in result["checks"]}
    for key in ("cover", "table_meta", "groups", "header", "rows", "completeness", "source_notes"):
        assert checks[key]["ok"] is True, key
    assert checks["placeholders"]["severity"] == "info"
    assert result["summary"]["blocking_failed"] == 0


def test_missing_group_pair_fails_with_clear_key():
    def mutate(sheet):
        # 把「溯源-监管集市」标题改掉：业务口径还在，溯源不在 → 分组不再成对
        for row in range(1, 20):
            for column in range(1, sheet.max_column + 1):
                cell = sheet.cell(row=row, column=column)
                if str(cell.value or "").strip() == "溯源-监管集市":
                    cell.value = "溯源"

    result = check_survey_structure(_mutate(export_survey_document(_content()), mutate))
    assert result["verdict"] == "fail"
    assert result["failed_keys"] == ["groups"]


def test_header_label_change_fails_header_check_only():
    def mutate(sheet):
        for row in range(1, 20):
            for column in range(1, sheet.max_column + 1):
                cell = sheet.cell(row=row, column=column)
                if str(cell.value or "").strip() == "数据项编码":
                    cell.value = "字段编码"

    result = check_survey_structure(_mutate(export_survey_document(_content()), mutate))
    assert "header" in result["failed_keys"]
    # 列名行找不到了，数据行也就无从判断；这是结构被破坏的真实后果，不做"部分通过"粉饰
    assert "rows" in result["failed_keys"]


def test_missing_completeness_footer_fails():
    def mutate(sheet):
        # 清空完整度标题行：既不冒充数据行，也能证明"缺了完整度统计"会被单独判定
        for row in range(1, sheet.max_row + 1):
            if "完整度" in str(sheet.cell(row=row, column=1).value or ""):
                sheet.cell(row=row, column=1).value = None

    result = check_survey_structure(_mutate(export_survey_document(_content()), mutate))
    assert result["failed_keys"] == ["completeness"]


def test_invalid_field_code_fails_rows_check():
    def mutate(sheet):
        for row in range(1, sheet.max_row + 1):
            cell = sheet.cell(row=row, column=1)
            if str(cell.value or "").strip() == "H010001":
                cell.value = "借据ID"

    result = check_survey_structure(_mutate(export_survey_document(_content()), mutate))
    assert "rows" in result["failed_keys"]


def test_unreadable_payload_is_reported_not_swallowed():
    with pytest.raises(StructureCheckError) as caught:
        check_survey_structure(b"not-an-xlsx")
    assert caught.value.code == "artifact_not_readable"
    with pytest.raises(StructureCheckError) as empty:
        check_survey_structure(b"")
    assert empty.value.code == "artifact_empty"

def test_contract_follows_renderer_generation():
    """历史产物要按"渲染时的结构"判定，不能被后加的结构要求判成不合格。"""
    newest = contract_for_renderer("survey-requirement-doc-v9+afe4fe6ada0d")
    assert newest["version"] == STRUCTURE_CONTRACT_VERSION
    assert newest["generation"] == 9
    assert newest["required_keys"] == [
        "cover", "table_meta", "groups", "header", "rows", "completeness", "source_notes",
    ]

    v8 = contract_for_renderer("survey-requirement-doc-v8")
    assert "completeness" in v8["required_keys"]
    assert "source_notes" not in v8["required_keys"]

    legacy = contract_for_renderer("survey-requirement-doc-v7")
    assert legacy["required_keys"] == ["cover", "table_meta", "groups", "header", "rows"]

    # 标准版式与 Word 产物不是一表通调研表式，不套用任何结构契约
    assert contract_for_renderer("builtin-xlsx-v1") is None
    assert contract_for_renderer(None) is None


def test_old_artifact_passes_under_its_own_contract():
    """真实证据：产物 #20 渲染于完整度/来源说明之前，按当时的契约它是合规的。"""
    payload = export_survey_document(_content())
    result = check_survey_structure(payload, renderer_version="survey-requirement-doc-v7")
    assert result["verdict"] == "pass"
    assert result["failed_keys"] == []
    assert result["skipped_keys"] == ["completeness", "source_notes"]
    assert result["summary"]["blocking_total"] == 5
    checks = {item["key"]: item for item in result["checks"]}
    # 降级为信息项，但结论仍然可见，不假装它存在
    assert checks["completeness"]["severity"] == "info"
    assert "该版本渲染时还没有这项尾注" in checks["completeness"]["detail"]
    # 这份 payload 是当前导出器产出的，尾注在场；"在场"与"该项不属于该契约"是两件事，
    # 所以 true 也不能让它进入 blocking 统计
    assert checks["completeness"]["ok"] is True
    assert checks["completeness"]["key"] not in result["failed_keys"]


def test_v8_contract_still_requires_completeness():
    payload = export_survey_document(_content())

    def mutate(sheet):
        for row in range(1, sheet.max_row + 1):
            if "完整度" in str(sheet.cell(row=row, column=1).value or ""):
                sheet.cell(row=row, column=1).value = None

    broken = _mutate(payload, mutate)
    result = check_survey_structure(broken, renderer_version="survey-requirement-doc-v8")
    assert result["verdict"] == "fail"
    assert result["failed_keys"] == ["completeness"]
    assert result["skipped_keys"] == ["source_notes"]


def test_non_survey_renderer_is_refused_not_scored():
    with pytest.raises(StructureCheckError) as caught:
        check_survey_structure(b"whatever", renderer_version="builtin-xlsx-v1")
    assert caught.value.code == "artifact_not_survey"
    assert "一表通调研表式" in caught.value.message

def test_legacy_pass_carries_upgrade_hint():
    """按旧契约通过要说明"通过"是按旧版式通过的，不能让人以为旧文件已达到当前版式。"""
    payload = export_survey_document(_content())
    old = check_survey_structure(payload, renderer_version="survey-requirement-doc-v6")
    assert old["verdict"] == "pass"
    hint = old["upgrade_hint"]
    assert hint and "v6 渲染器" in hint and "完整度统计与来源说明" in hint
    assert "历史文件不会被覆盖" in hint

    v8 = check_survey_structure(payload, renderer_version="survey-requirement-doc-v8")
    assert v8["upgrade_hint"] and "来源说明" in v8["upgrade_hint"]
    assert "完整度统计与来源说明" not in v8["upgrade_hint"]

    current = check_survey_structure(payload, renderer_version="survey-requirement-doc-v9+afe4fe6ada0d")
    assert current["upgrade_hint"] is None
