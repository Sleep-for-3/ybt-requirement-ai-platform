"""解析器升级后重算既有模板版本的解析快照（默认只报告，不写库）。

为什么需要它：模板版本的 ``parsed_snapshot_json`` 是导入时写下的快照，解析器修好之后
旧版本不会自动重算；而"集市列重复多组"这类修复会显著改变集市映射条数。为了避免
"代码修好了、库里的快照还是旧的"，这里提供显式重算入口：

    python scripts/reparse_template_version.py --template-version-id 2            # 只报告
    python scripts/reparse_template_version.py --template-version-id 2 --commit   # 写库

写库只更新该版本的 ``parsed_snapshot_json`` / ``sheet_names_json`` / ``parse_report_json`` /
``parse_status``，不改文件、不改其他版本；是否重新 Apply 由调用方决定。
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.models import TemplateVersion  # noqa: E402
from app.services.storage.factory import get_storage_service  # noqa: E402
from app.services.template_parser import SurveyTemplateParser, is_survey_workbook  # noqa: E402
from app.services.template_parser.excel_parser import ExcelTemplateParser  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-version-id", type=int, required=True)
    parser.add_argument("--commit", action="store_true", help="写回数据库（默认只报告）")
    args = parser.parse_args()

    with SessionLocal() as db:
        version = db.get(TemplateVersion, args.template_version_id)
        if version is None:
            print(f"模板版本不存在：{args.template_version_id}")
            return 1
        if not version.storage_path:
            print("该版本没有存储路径，无法重算")
            return 1
        data = get_storage_service().read(version.storage_path)
        before_sheets = len(version.parsed_snapshot_json or [])
        before_fields = sum(len((sheet or {}).get("rows") or []) for sheet in version.parsed_snapshot_json or [])
        before_mart = sum(
            len([row for row in (sheet or {}).get("rows") or [] if row.get("mart_table_code") or row.get("mart_field_code")])
            for sheet in version.parsed_snapshot_json or []
        )
        survey = is_survey_workbook(BytesIO(data))
        output = (SurveyTemplateParser() if survey else ExcelTemplateParser()).parse(BytesIO(data))
        snapshot = [
            {"sheet_name": result.sheet_name, "table_code": result.table_code, "table_name": result.table_name,
             "field_count": result.field_count, "rows": result.parsed_rows, "warnings": result.warnings}
            for result in output.results
        ]
        after_fields = sum(len(sheet["rows"]) for sheet in snapshot)
        after_mart = sum(
            1 for sheet in snapshot for row in sheet["rows"]
            if row.get("mart_table_code") or row.get("mart_field_code")
        )
        mapping_rows = sum(len(row.get("mart_mappings") or []) for sheet in snapshot for row in sheet["rows"])
        print(f"version={version.id} survey={survey} reader={output.parse_report.get('reader') if output.parse_report else '-'}")
        print(f"  工作表：{before_sheets} → {len(snapshot)}；字段：{before_fields} → {after_fields}")
        print(f"  有集市列的字段行：{before_mart} → {after_mart}；集市映射条数（新解析）：{mapping_rows}")
        print(f"  parse_report：blocking={output.parse_report.get('blocking_count') if output.parse_report else '-'} "
              f"findings={len(output.parse_report.get('findings') or []) if output.parse_report else '-'}")
        if not args.commit:
            print(f"表级口径 {len(getattr(output, 'table_meta', {}) or {})} 张表")
            print("（只报告；加 --commit 才会写回数据库）")
            return 0
        version.parsed_snapshot_json = snapshot
        version.sheet_names_json = [result.sheet_name for result in output.results]
        version.parse_report_json = output.parse_report or {}
        # 表级口径（主题/填报说明/报送数据域）：调研表里已有的事实，重算时一并写回，
        # 否则导出文档第 3-8 行只能继续写“待业务补充”。
        version.table_meta_json = getattr(output, "table_meta", {}) or {}
        version.parse_status = "success"
        db.commit()
        print("已写回数据库；如需让集市映射生效请再执行模板 Apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
