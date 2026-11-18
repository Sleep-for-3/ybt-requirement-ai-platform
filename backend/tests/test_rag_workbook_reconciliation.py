import json
import sys

import pytest

from scripts import rag_workbook_reconciliation as reconciliation


def test_missing_cell_summary_is_grouped_and_omits_source_values():
    missing = [
        {"sheet": "穿透层问答", "row": 3, "column": "L", "header": "具体问题描述",
         "semantic_field": "question", "value": "sensitive question"},
        {"sheet": "穿透层问答", "row": 4, "column": "L", "header": "具体问题描述",
         "semantic_field": "question", "value": "another sensitive question"},
        {"sheet": "穿透层问答", "row": 6, "column": "H", "header": "数据项/指标编码",
         "semantic_field": "field_code", "value": "sensitive-code"},
    ]

    summary = reconciliation.summarize_missing_cells(missing)

    assert summary == [
        {"sheet": "穿透层问答", "column": "H", "header": "数据项/指标编码",
         "semantic_field": "field_code", "missing_cell_count": 1, "first_row": 6,
         "last_row": 6},
        {"sheet": "穿透层问答", "column": "L", "header": "具体问题描述",
         "semantic_field": "question", "missing_cell_count": 2, "first_row": 3,
         "last_row": 4},
    ]
    assert "value" not in json.dumps(summary, ensure_ascii=False)
    assert "sensitive" not in json.dumps(summary, ensure_ascii=False)


def test_cli_refuses_to_overwrite_existing_reconciliation_evidence(tmp_path, monkeypatch):
    output = tmp_path / "existing.json"
    output.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "rag_workbook_reconciliation.py",
        "--source", str(tmp_path / "source.xlsx"),
        "--project-id", "1",
        "--document-id", "1",
        "--version-id", "1",
        "--output", str(output),
    ])

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        reconciliation.main()

    assert output.read_text(encoding="utf-8") == "preserve"
