"""一表通调研表解析器与模板 Apply 的离线回归测试。

所有工作簿都在 ``tmp_path`` 里用 openpyxl 现场合成，不依赖客户桌面上的真实模板，
因此可以离线、重复运行。

测试固定的是"一表通调研表"版式的契约：

* 第 1 行是"返回"链接，第 2 行是合并分区表头，第 3 行才是列名，
  第 4 行是稀疏填写说明，数据自第 5 行起；
* 说明性 sheet 不产出表，只留下 info 级 finding；
* 缺关键列是 blocking 且不产出表，缺行键是 warning，重复"备注"按出现次序映射。
"""

from __future__ import annotations

from openpyxl import Workbook

from app.models import Project
from app.services.template_parser.survey_excel_parser import (
    SURVEY_CONFIG_VERSION,
    SurveyTemplateParser,
    is_survey_workbook,
)

TABLE_SHEET = "T_8_1-贷款借据"

MAIN_HEADER = [
    "表编号",
    "表名称",
    "数据项编码",
    "数据项名称",
    "制度包版本",
    "数据类别",
    "数据格式",
    "数据项监管要求",
    "是否必填",
    "取值业务口径描述",
    "备注",
    "集市表中文名",
    "集市表英文名",
    "集市字段中文名",
    "集市字段英文名",
    "数据项取数逻辑",
]

MAIN_ROWS = [
    [
        "T_8_1",
        "贷款借据",
        "H010001",
        "借据ID",
        "R2022100101",
        "基础数据",
        "字符型",
        "填报该笔贷款对应的借据号码，最大长度不超过28位。",
        "是",
        "取借据号",
        "业务备注一",
        "信贷借据信息表",
        "HYF_LN_DUEBILL_INFO",
        "信贷借据号",
        "DUEBILL_NO",
        "",
    ],
    [
        "T_8_1",
        "贷款借据",
        "H010010",
        "借款余额",
        "R2022100101",
        "基础数据",
        "数值型",
        "填报该笔借据截至业务日期的借款余额。",
        "否",
        "取贷款余额",
        "",
        "信贷借据信息表",
        "HYF_LN_DUEBILL_INFO",
        "借款余额",
        "LOAN_BAL",
        "",
    ],
    [
        "T_8_1",
        "贷款借据",
        "H010019",
        "贷款状态",
        "R2022100101",
        "基础数据",
        "字符型",
        "填报该笔借据当前所处的贷款状态。",
        "否",
        "按状态码转换",
        "",
        "信贷借据信息表",
        "HYF_LN_DUEBILL_INFO",
        "贷款状态",
        "LOAN_STATUS",
        "01 正常 / 02 逾期 按码值表转换",
    ],
]


def _add_table_sheet(workbook: Workbook, title: str, header: list[str], rows: list[list[str]]) -> None:
    sheet = workbook.create_sheet(title)
    sheet.cell(row=1, column=1, value="返回")
    total = len(header)
    split = max(1, total // 2)
    sheet.cell(row=2, column=1, value="数据表信息")
    if split > 1:
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=split)
    if split < total:
        sheet.cell(row=2, column=split + 1, value="业务与技术口径")
        sheet.merge_cells(start_row=2, start_column=split + 1, end_row=2, end_column=total)
    for column, name in enumerate(header, start=1):
        sheet.cell(row=3, column=column, value=name)
    # 第 4 行是稀疏的填写说明；放在末列（非关键列），不会变成一条数据。
    sheet.cell(row=4, column=total, value="填写说明：请按列名逐项填写")
    for row_number, values in enumerate(rows, start=5):
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_number, column=column, value=value)


MULTI_MART_HEADER = MAIN_HEADER + [
    "集市表中文名",
    "集市表英文名",
    "集市字段中文名",
    "集市字段英文名",
    "数据项取数逻辑",
]

MULTI_MART_ROWS = [
    [
        "T_8_1", "贷款借据", "H010001", "借据ID", "R2022100101", "基础数据", "字符型",
        "填报该笔贷款对应的借据号码。", "是", "取借据号", "",
        "信贷借据信息表", "HYF_LN_DUEBILL_INFO", "信贷借据号", "DUEBILL_NO", "",
        "贴现票据信息表", "HYF_LN_BILL_INFO", "票据号码", "BILL_NO", "BILL_NO AS H010001",
    ],
]


def test_repeated_mart_columns_keep_every_mapping(tmp_path):
    """真实调研表同一 sheet 里集市列会重复多组，每组都是一个独立集市映射。

    老实现只认第一组，第二组及之后的“集市表英文名/集市字段英文名/取数逻辑”会被当成
    未识别列丢掉——字段看起来只有一个溯源，实际模板写了两个。这里固定"每组都要保留"。
    """

    path = _build(tmp_path / "multi_mart.xlsx", with_directory=False,
                  header=MULTI_MART_HEADER, rows=MULTI_MART_ROWS)
    output = SurveyTemplateParser().parse(path)
    rows = output.results[0].parsed_rows
    assert len(rows) == 1
    mappings = rows[0]["mart_mappings"]
    assert [item["mart_table_code"] for item in mappings] == ["HYF_LN_DUEBILL_INFO", "HYF_LN_BILL_INFO"]
    assert [item["mart_field_code"] for item in mappings] == ["DUEBILL_NO", "BILL_NO"]
    assert mappings[1]["mart_logic"] == "BILL_NO AS H010001"
    # 重复组不应再出现在“未识别列”里（否则界面会显示"有 N 列不在已知口径内"）。
    report = output.parse_report
    codes = [item["code"] for item in report["findings"]]
    # 允许“已识别监管集市列”这类 info 提示，但绝不能出现“有 N 列不在已知口径内”。
    assert "unrecognized_column" not in codes
    assert codes == ["merged_header"]
    # 顶层 ``complete`` 表示“没有解析损失”（合并表头会算信息级损失），这里只要求不阻断。
    assert report["blocking_count"] == 0


def _add_directory_sheet(workbook: Workbook) -> None:
    sheet = workbook.create_sheet("目录")
    sheet.cell(row=1, column=1, value="目录")
    sheet.cell(row=2, column=1, value="T_8_1-贷款借据")
    sheet.cell(row=2, column=2, value="贷款借据表")


def _build(path, *, with_directory: bool = True, header=None, rows=None):
    workbook = Workbook()
    workbook.remove(workbook.active)
    if with_directory:
        _add_directory_sheet(workbook)
    _add_table_sheet(
        workbook,
        TABLE_SHEET,
        list(header if header is not None else MAIN_HEADER),
        [list(row) for row in (rows if rows is not None else MAIN_ROWS)],
    )
    workbook.save(path)
    return path


def _build_legacy(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "T_1_1"
    for column, name in enumerate(["表编号", "表名称", "字段代码", "字段名称", "是否必填", "业务定义"], start=1):
        sheet.cell(row=1, column=column, value=name)
    for column, value in enumerate(["T_1_1", "机构信息", "A010001", "机构ID", "是", "机构唯一编码"], start=1):
        sheet.cell(row=2, column=column, value=value)
    workbook.save(path)
    return path


def _parse(path):
    return SurveyTemplateParser().parse(str(path))


def test_detects_survey_layout_but_not_legacy(tmp_path) -> None:
    assert is_survey_workbook(str(_build(tmp_path / "survey.xlsx"))) is True
    assert is_survey_workbook(str(_build_legacy(tmp_path / "legacy.xlsx"))) is False


def test_parses_headers_after_section_row(tmp_path) -> None:
    output = _parse(_build(tmp_path / "survey.xlsx"))

    assert output.table_count == 1
    assert output.field_count == 3
    sheet = output.results[0]
    assert (sheet.table_code, sheet.table_name) == ("T_8_1", "贷款借据")
    first = sheet.parsed_rows[0]
    assert first["field_code"] == "H010001"
    assert first["field_name"] == "借据ID"
    assert first["required_flag"] == "是"
    assert "最大长度不超过28位" in first["regulatory_original_definition"]
    assert first["data_category"] == "基础数据"
    assert first["mart_table_code"] == "HYF_LN_DUEBILL_INFO"
    assert first["mart_field_code"] == "DUEBILL_NO"
    assert sheet.parsed_rows[1]["required_flag"] == "否"
    assert sheet.parsed_rows[2]["mart_logic"].startswith("01 正常")


def test_directory_sheet_is_info_only(tmp_path) -> None:
    output = _parse(_build(tmp_path / "survey.xlsx"))

    assert [item.sheet_name for item in output.results] == [TABLE_SHEET]
    assert output.parse_report["sheets_skipped"][0]["sheet"] == "目录"
    severities = {
        item["severity"]
        for item in output.parse_report["findings"]
        if (item.get("locator") or {}).get("sheet") == "目录"
    }
    assert severities == {"info"}
    assert output.parse_report["blocking_count"] == 0


def test_missing_field_code_column_is_blocking_without_table(tmp_path) -> None:
    path = _build(
        tmp_path / "missing_code.xlsx",
        with_directory=False,
        header=["数据项名称", "数据项监管要求", "备注"],
        rows=[["字段甲", "要求甲", "备注甲"]],
    )
    output = _parse(path)

    assert output.table_count == 0
    assert output.results == []
    blocking = [item for item in output.parse_report["findings"] if item["severity"] == "blocking"]
    assert any(item["code"] == "critical_column_missing" for item in blocking)


def test_row_without_field_code_is_warned_and_skipped(tmp_path) -> None:
    rows = [
        list(MAIN_ROWS[0]),
        ["T_8_1", "贷款借据", "", "缺编码字段", "R2022100101", "", "", "", "否", "", "", "", "", "", "", ""],
    ]
    output = _parse(_build(tmp_path / "missing_row_key.xlsx", with_directory=False, rows=rows))

    assert output.results[0].field_count == 1
    codes = [item["code"] for item in output.parse_report["findings"]]
    assert "row_missing_key" in codes


def test_duplicate_remark_columns_keep_both_values(tmp_path) -> None:
    header = ["表编号", "表名称", "数据项编码", "数据项名称", "是否必填", "备注", "备注"]
    rows = [["T_8_1", "贷款借据", "H010001", "借据ID", "是", "业务侧备注", "技术侧备注"]]
    output = _parse(_build(tmp_path / "dup_remark.xlsx", with_directory=False, header=header, rows=rows))

    remarks = output.results[0].parsed_rows[0]["remarks"]
    assert "业务侧备注" in remarks
    assert "技术侧备注" in remarks


def test_parse_report_metadata(tmp_path) -> None:
    report = _parse(_build(tmp_path / "survey.xlsx")).parse_report

    assert report["reader"] == "survey-template"
    assert report["config_version"] == SURVEY_CONFIG_VERSION
    assert report["sheet_total"] == 2
    assert report["sheet_parsed"] == 1
    assert report["row_emitted"] == 3
    assert report["blocking_count"] == 0


def test_non_identifier_mart_code_is_kept_as_text(tmp_path) -> None:
    rows = [list(MAIN_ROWS[0])]
    rows[0][14] = "CASE WHEN P1.T = '08' THEN '银行承兑汇票' ELSE '00000000' END"
    output = _parse(_build(tmp_path / "expr_mart.xlsx", with_directory=False, rows=rows))

    assert output.results[0].parsed_rows[0]["mart_field_code"].startswith("CASE WHEN")


def test_project_model_import_guard() -> None:
    """确保测试模块自身的模型导入可用（防止夹具腐坏时静默跳过）。"""

    assert Project.__tablename__ == "projects"


def test_table_level_sheet_feeds_table_meta_without_touching_field_rows(tmp_path):
    """“表级口径”sheet 里的主题/填报说明/报送数据域必须被解析出来。

    真实调研表把这三项放在独立的“表级口径”sheet 里，而不是每个字段行上；
    如果解析器忽略它，导出文档第 3-8 行就只能写“待业务补充”，
    把模板里本来就有的事实丢掉。
    """

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = TABLE_SHEET
    sheet.append(["返回"])
    sheet.append(["数据表信息"] * 4)
    sheet.append(["表编号", "表名称", "数据项编码", "数据项名称"])
    sheet.append([None, None, None, None])
    sheet.append(["T_8_1", "贷款借据", "H010001", "借据ID"])

    meta_sheet = workbook.create_sheet("表级口径")
    meta_sheet.append(
        ["主题", "表编号", "数据表名称", "填报说明", "报送数据域编码", "报送数据域名称"]
    )
    meta_sheet.append(
        ["状态类数据", "T_8_1", "贷款借据", "全量借据", "00000000", "默认报送数据域"]
    )
    meta_sheet.append(["机构类数据", "T_1_1", "机构信息", "", "010101", "存款_个人存款"])
    path = tmp_path / "survey.xlsx"
    workbook.save(path)

    output = _parse(path)

    assert output.field_count == 1
    assert output.table_meta["T_8_1"]["theme"] == "状态类数据"
    assert output.table_meta["T_8_1"]["reporting_domain_name"] == "默认报送数据域"
    assert output.table_meta["T_8_1"]["filing_note"] == "全量借据"
    # 填报说明为空时不写空串冒充“已确认”
    assert "filing_note" not in output.table_meta["T_1_1"]
    assert output.table_meta["T_1_1"]["theme"] == "机构类数据"