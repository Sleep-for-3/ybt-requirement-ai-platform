"""一次性补丁：在场景导出测试里补一条"11 个基础列名与客户示例逐字一致"的断言。"""
from pathlib import Path

TARGET = Path("tests/test_requirement_survey_export_scenarios.py")
NEW_TEST = '''def test_base_headers_match_customer_example():
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


'''


def main() -> None:
    text = TARGET.read_bytes().decode("utf-8").replace("\r\n", "\n")
    anchor = "def test_without_scenario_data_layout_falls_back_to_source_systems():\n"
    if NEW_TEST in text:
        print("already patched")
        return
    if anchor not in text:
        raise SystemExit("anchor missing")
    text = text.replace(anchor, NEW_TEST + anchor, 1)
    TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print("patched", TARGET)


if __name__ == "__main__":
    main()
