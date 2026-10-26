"""把 T_5_1 的场景口径与溯源补成第四份受治理知识文档（演示数据）。

背景：m1_v3 评测里 scenario 类问题 Recall@5 只有 0.056——场景口径只写在
requirement 内容里，知识库里没有任何"场景 + 字段 + 来源系统 + 处理逻辑"的单元，
检索自然召不回来。本脚本从 requirement 30 的 ``document_content`` 读
``scenario_groups``（3 个场景 × 18 字段的 AI 草稿口径与溯源），生成
``T_5_1_场景口径与溯源.xlsx`` 并走真实 API 上传、审核激活、项目级重建索引。

红线：单元正文取自 ``ai_generated_content``（AI 草稿），并在正文首行显式标注
"演示数据（AI 生成草稿），可被人工覆盖"，不冒充已确认口径。

用法：
    python scripts/knowledge_seed_scenarios.py            # dry-run，只打印计数
    python scripts/knowledge_seed_scenarios.py --apply    # 上传 + 激活 + 重建索引
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import Workbook

from knowledge_seed_t51 import (
    OUT_DIR,
    PROJECT_ID,
    _request,
    _save,
    _session,
    activate,
    ensure_document,
    load_requirement_content,
)

LOGICAL_CODE = "ybt-t51-scenarios-20261026"
PUBLISHER = "一表通监管报送（演示场景口径）"
CHANGE_NOTE = "T_5_1 场景口径与溯源（round 75 检索证据底座；演示数据，可被人工覆盖）"
SHEET_NAME = "场景口径"

HEADERS = [
    "数据项编码",
    "数据项名称",
    "业务场景",
    "业务口径",
    "来源系统",
    "来源表英文名",
    "来源表中文名",
    "来源字段英文名",
    "来源字段中文名",
    "处理逻辑",
    "处理逻辑类型",
    "备注",
]

DEMO_MARK = "演示数据（AI 生成草稿），可被人工覆盖，未经业务确认不得视为已确认"


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _first(*values) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def scenario_rows(content: dict) -> list[dict]:
    fields: dict[int, dict] = {}
    for record in content.get("fields") or []:
        field = record.get("field") or {}
        if field.get("id") and field.get("field_code"):
            fields[int(field["id"])] = field
    rows: list[dict] = []
    for group in content.get("scenario_groups") or []:
        scenario_name = _text(group.get("scenario_name")) or _text(group.get("scenario_code"))
        if not scenario_name:
            continue
        business = {int(item["target_field_id"]): item for item in group.get("business") or [] if item.get("target_field_id")}
        technical = {int(item["target_field_id"]): item for item in group.get("technical") or [] if item.get("target_field_id")}
        for field_id, field in fields.items():
            biz = business.get(field_id) or {}
            tech = technical.get(field_id) or {}
            if not biz and not tech:
                continue
            business_text = _first(biz.get("final_content"), biz.get("ai_generated_content"), biz.get("business_definition"))
            logic_text = _first(tech.get("final_content"), tech.get("ai_generated_content"), tech.get("processing_logic"))
            source_system = _first(tech.get("source_system_name"))
            source_table_en = _first(tech.get("source_table_english_name"))
            source_table_cn = _first(tech.get("source_table_chinese_name"))
            source_field_en = _first(tech.get("source_field_english_name"))
            source_field_cn = _first(tech.get("source_field_chinese_name"))
            if not (business_text or logic_text or source_table_en):
                continue
            rows.append(
                {
                    "数据项编码": field["field_code"],
                    "数据项名称": _text(field.get("field_name")),
                    "业务场景": scenario_name,
                    "业务口径": f"{DEMO_MARK}：{business_text}" if business_text else "",
                    "来源系统": source_system,
                    "来源表英文名": source_table_en,
                    "来源表中文名": source_table_cn,
                    "来源字段英文名": source_field_en,
                    "来源字段中文名": source_field_cn,
                    "处理逻辑": f"{DEMO_MARK}：{logic_text}" if logic_text else "",
                    "处理逻辑类型": _first(tech.get("processing_logic_type"), "加工" if logic_text else ""),
                    "备注": _first(tech.get("remarks"), biz.get("remarks"), DEMO_MARK),
                }
            )
    return rows


def build_workbook(rows: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "T_5_1_场景口径与溯源.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    sheet.append(HEADERS)
    for row in rows:
        sheet.append([row.get(header, "") for header in HEADERS])
    _save(workbook, path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-reindex", action="store_true")
    args = parser.parse_args()

    content = load_requirement_content()
    rows = scenario_rows(content)
    scenarios = sorted({row["业务场景"] for row in rows})
    path = build_workbook(rows)
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "rows": len(rows),
        "scenarios": scenarios,
        "fields": sorted({row["数据项编码"] for row in rows}),
        "file": str(path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        if len(rows) == 0:
            raise SystemExit("no scenario rows built")
        return

    session = _session()
    document = ensure_document(
        session,
        path,
        knowledge_type="business_research",
        source_category="business_material",
        logical_code=LOGICAL_CODE,
        publisher=PUBLISHER,
        change_note=CHANGE_NOTE,
    )
    document_id = int(document["id"])
    version = activate(session, document_id)
    print(
        json.dumps(
            {
                "document_id": document_id,
                "version": version["id"],
                "lifecycle_status": version.get("lifecycle_status"),
                "parse_status": version.get("parse_status"),
                "unit_count": (version.get("parse_summary_json") or {}).get("unit_count"),
            },
            ensure_ascii=False,
        )
    )
    if not args.skip_reindex:
        response = _request(
            session,
            "POST",
            f"/projects/{PROJECT_ID}/semantic-index/reindex",
            json={"force": True, "chunk_strategy": "knowledge-fragment-v1", "fragment_max_tokens": 240},
        )
        if response.status_code >= 300:
            raise SystemExit(f"reindex failed: {response.status_code} {response.text[:400]}")
        payload = response.json()
        print(json.dumps({"reindex": payload}, ensure_ascii=False))

    print(json.dumps({"documents": [{"document_id": document_id, "file": str(path)}], "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
