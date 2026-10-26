r"""Seed project 9 with T_5_1 evidence for retrieval evaluation (M1).

Builds two governed knowledge workbooks from sources that already exist in the
repository / database, uploads them through the real API, approves and activates
the versions, and rebuilds the project semantic index.  Nothing is written to the
knowledge base without going through the documented review path.

Sources:
* ``C:/Users/李儒伟/Desktop/需求文档输出示例.xlsx`` — regulatory caliber text for
  E010001..E010018 (customer sample document).
* requirement 30 frozen content — batch-script lineage rules and mart mappings.

Usage::

    cd backend
    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe scripts\knowledge_seed_t51.py           # dry-run
    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe scripts\knowledge_seed_t51.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import OrderedDict
from pathlib import Path

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.core.database import SessionLocal
from app.models import Requirement
from app.services.requirement_scope import document_content

PROJECT_ID = 9
REQUIREMENT_ID = 30
EXAMPLE = Path("C:/Users/李儒伟/Desktop/需求文档输出示例.xlsx")
BASE = "http://127.0.0.1:8011/api"
TOKEN_FILE = Path(__file__).resolve().parent / "out" / "probe" / "token.txt"
OUT_DIR = Path(__file__).resolve().parent / "out" / "knowledge"

HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
STRIP = re.compile(r"^(?P<name>.*?)[（(](?P<code>[^（()）]*)[）)]\s*$")


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _split_summary(value) -> tuple[str, str]:
    text = _clean(value)
    if not text:
        return "", ""
    match = STRIP.match(text)
    if match:
        return match.group("name").strip(), match.group("code").strip()
    return text, ""


def load_example_fields() -> "OrderedDict[str, dict]":
    workbook = load_workbook(EXAMPLE, data_only=True)
    sheet = workbook["Sheet1"]
    fields: "OrderedDict[str, dict]" = OrderedDict()
    for row in range(12, sheet.max_row + 1):
        code = _clean(sheet.cell(row, 1).value)
        if not re.fullmatch(r"E01\d{4}", code):
            continue
        if code in fields:
            continue
        fields[code] = {
            "name": _clean(sheet.cell(row, 2).value),
            "category": _clean(sheet.cell(row, 3).value),
            "format": _clean(sheet.cell(row, 4).value),
            "original": _clean(sheet.cell(row, 5).value),
            "refined": _clean(sheet.cell(row, 6).value),
            "report_name": _clean(sheet.cell(row, 7).value),
            "report_field": _clean(sheet.cell(row, 8).value),
            "east": _clean(sheet.cell(row, 9).value),
            "internal": _clean(sheet.cell(row, 10).value),
            "row": row,
        }
    return fields


def load_requirement_content() -> dict:
    db = SessionLocal()
    try:
        requirement = db.get(Requirement, REQUIREMENT_ID)
        if requirement is None:
            raise SystemExit(f"requirement {REQUIREMENT_ID} not found")
        return json.loads(json.dumps(document_content(db, requirement), ensure_ascii=False))
    finally:
        db.close()


def script_rows(content: dict) -> list[dict]:
    rules = ((content.get("script_basis") or {}).get("rules") or [])
    by_target: "OrderedDict[str, list[dict]]" = OrderedDict()
    for rule in rules:
        target = (rule.get("target") or {}).get("column_name")
        if not target:
            continue
        by_target.setdefault(target, []).append(rule)
    rows: list[dict] = []
    for field in content.get("fields") or []:
        code = _clean((field.get("field") or {}).get("field_code"))
        name = _clean((field.get("field") or {}).get("field_name"))
        field_rules = by_target.get(code) or []
        if not field_rules:
            continue
        sources: list[str] = []
        for rule in field_rules:
            for source in rule.get("sources") or []:
                text = _clean(source.get("table_name")) + "." + _clean(source.get("column_name"))
                if text.strip(".") and text not in sources:
                    sources.append(text)
        expressions = [_clean(rule.get("transformation_expression")) for rule in field_rules]
        expressions = [item for item in expressions if item]
        logic = expressions[0] if expressions else "脚本直接取数，无显式表达式"
        if len(expressions) > 1:
            logic += f"（另有 {len(expressions) - 1} 个分支表达式）"
        logic_type = "加工" if len(expressions) > 1 or "case" in logic.lower() else "直取"
        rows.append({
            "code": code,
            "name": name,
            "sources": "；".join(sources[:6]) or "脚本未登记来源字段",
            "logic": logic[:1500],
            "logic_type": logic_type,
            "rule_count": len(field_rules),
        })
    return rows


def mapping_rows(content: dict) -> list[dict]:
    rows: list[dict] = []
    for field in content.get("fields") or []:
        code = _clean((field.get("field") or {}).get("field_code"))
        name = _clean((field.get("field") or {}).get("field_name"))
        for mapping in field.get("mart_mappings") or []:
            table_name, table_code = _split_summary(mapping.get("mart_table_summary"))
            field_name, field_code = _split_summary(mapping.get("mart_field_summary"))
            rows.append({
                "code": code,
                "name": name,
                "mart_table": _clean(mapping.get("mart_table_summary")),
                "mart_field": _clean(mapping.get("mart_field_summary")),
                "table_name": table_name or table_code,
                "field_name": field_name or field_code,
                "rule": _clean(mapping.get("business_rule") or mapping.get("final_content")),
            })
    return rows


def build_regulatory_workbook(fields: "OrderedDict[str, dict]") -> tuple[Path, int]:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "监管口径"
    headers = ["数据项编码", "数据项名称", "一表通表", "口径类型", "监管口径正文", "来源文件", "来源行"]
    sheet.append(headers)
    count = 0
    for code, item in fields.items():
        for kind, text in (
            ("监管原始口径", item["original"]),
            ("监管定义细化", item["refined"]),
            ("EAST口径", item["east"]),
            ("行内定义", item["internal"]),
        ):
            if not text:
                continue
            sheet.append([code, item["name"], "T_5_1", kind, text, "需求文档输出示例.xlsx", item["row"]])
            count += 1
    profile = workbook.create_sheet("字段画像")
    profile.append(["数据项编码", "数据项名称", "一表通表", "数据类别", "数据格式", "报表名称", "字段名称", "来源文件"])
    for code, item in fields.items():
        profile.append([code, item["name"], "T_5_1", item["category"], item["format"], item["report_name"], item["report_field"], "需求文档输出示例.xlsx"])
        count += 1
    path = OUT_DIR / "T_5_1_监管口径与字段画像.xlsx"
    _save(workbook, path)
    return path, count


def build_lineage_workbook(scripts: list[dict], mappings: list[dict]) -> tuple[Path, int]:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "跑批脚本血缘"
    sheet.append(["数据项编码", "数据项名称", "一表通表", "来源系统", "来源表英文名", "来源字段英文名", "处理逻辑", "处理逻辑类型", "规则条数"])
    for row in scripts:
        sheet.append([
            row["code"], row["name"], "T_5_1", "GBASE 跑批脚本 YBT_T_5_1.sql",
            row["sources"], row["sources"], row["logic"], row["logic_type"], row["rule_count"],
        ])
    mart = workbook.create_sheet("集市映射")
    mart.append(["数据项编码", "数据项名称", "一表通表", "集市表", "集市字段", "映射说明"])
    for row in mappings:
        mart.append([row["code"], row["name"], "T_5_1", row["mart_table"], row["mart_field"], row["rule"]])
    path = OUT_DIR / "T_5_1_跑批脚本血缘与集市映射.xlsx"
    _save(workbook, path)
    return path, len(scripts) + len(mappings)


def build_rule_workbook(content: dict) -> tuple[Path, int]:
    rules = ((content.get("script_basis") or {}).get("rules") or [])
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "脚本规则明细"
    sheet.append(["数据项编码", "数据项名称", "一表通表", "来源系统", "来源表英文名", "来源字段英文名", "处理逻辑", "处理逻辑类型", "脚本行号"])
    count = 0
    for rule in rules:
        source = rule.get("source") or {}
        target = rule.get("target") or {}
        table_name = _clean(target.get("table_name")) or "T_5_1"
        source_table = ".".join(part for part in (_clean(source.get("schema_name")), _clean(source.get("table_name"))) if part)
        source_field = _clean(source.get("column_name")) or _clean(target.get("column_name")) or "脚本规则"
        target_field = _clean(target.get("column_name"))
        expression = _clean(rule.get("transformation_expression"))
        join_condition = _clean(rule.get("join_condition") or rule.get("filter_condition"))
        if not (expression or join_condition):
            continue
        logic_parts = []
        if expression:
            logic_parts.append(f"加工表达式：{expression}")
        if join_condition:
            logic_parts.append(f"关联/过滤条件：{join_condition}")
        sheet.append([
            target_field or source_field,
            f"{table_name} {target_field or source_field}（脚本规则 {rule.get('rule_id')}）",
            table_name,
            "GBASE 跑批脚本 YBT_T_5_1.sql",
            source_table,
            source_field,
            "\n".join(logic_parts)[:1600],
            "关联" if join_condition and not expression else "加工",
            f"{rule.get('source_line_start')}-{rule.get('source_line_end')}",
        ])
        count += 1
    path = OUT_DIR / "T_5_1_脚本规则明细.xlsx"
    _save(workbook, path)
    return path, count


def _save(workbook: Workbook, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for sheet in workbook.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        widths = {"A": 14, "B": 22, "C": 12, "D": 18, "E": 60, "F": 30, "G": 60, "H": 14, "I": 10}
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width
    workbook.save(path)


def _session() -> requests.Session:
    session = requests.Session()
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    session.headers["Authorization"] = f"Bearer {token}"
    session.headers["X-Requested-With"] = "knowledge-seed"
    return session


def _relogin(session: requests.Session) -> None:
    response = requests.post(f"{BASE}/auth/login", json={"username": "ybt-lead", "password": "Ybt#20261024lead"}, timeout=30)
    response.raise_for_status()
    token = response.json()["access_token"]
    TOKEN_FILE.write_text(token, encoding="utf-8")
    session.headers["Authorization"] = f"Bearer {token}"


def _request(session: requests.Session, method: str, path: str, **kwargs):
    response = session.request(method, f"{BASE}{path}", timeout=120, **kwargs)
    if response.status_code == 401:
        _relogin(session)
        response = session.request(method, f"{BASE}{path}", timeout=120, **kwargs)
    return response


def upload(session: requests.Session, path: Path, *, knowledge_type: str, source_category: str, logical_code: str, publisher: str, change_note: str) -> dict:
    payload_bytes = path.read_bytes()
    response = _request(
        session,
        "POST",
        f"/projects/{PROJECT_ID}/knowledge/documents/upload",
        files={"file": (path.name, payload_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "knowledge_type": knowledge_type,
            "knowledge_scope": "project",
            "source_category": source_category,
            "logical_code": logical_code,
            "publisher": publisher,
            "change_note": change_note,
            "confidentiality_level": "internal",
        },
    )
    if response.status_code >= 300:
        raise SystemExit(f"upload {path.name} failed: {response.status_code} {response.text[:400]}")
    payload = response.json()
    if "id" in payload and "document_status" not in payload:
        payload = wait_job(session, payload["id"])
    return payload


def wait_job(session: requests.Session, job_id: int, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = _request(session, "GET", f"/jobs/{job_id}")
        if response.status_code >= 300:
            raise SystemExit(f"job {job_id} status failed: {response.status_code} {response.text[:300]}")
        job = response.json()
        if job.get("status") in {"completed", "failed", "blocked"}:
            return job
        time.sleep(2)
    raise SystemExit(f"job {job_id} did not finish in {timeout}s")


def activate(session: requests.Session, document_id: int) -> dict:
    versions = _request(session, "GET", f"/knowledge/documents/{document_id}/versions", params={"project_id": PROJECT_ID}).json()
    version = max(versions, key=lambda item: item["version_no"])
    if version.get("parse_status") != "parsed":
        raise SystemExit(f"version {version['id']} parse_status={version.get('parse_status')} error={version.get('parse_error')}")
    steps = {
        "draft": "submit-review",
        "pending_review": "review",
        "approved": "activate",
    }
    for _ in range(4):
        if version["lifecycle_status"] == "active":
            break
        action = steps.get(version["lifecycle_status"])
        if action is None:
            raise SystemExit(f"version {version['id']} lifecycle_status={version['lifecycle_status']} cannot advance")
        response = _request(
            session,
            "POST",
            f"/knowledge/document-versions/{version['id']}/{action}",
            params={"project_id": PROJECT_ID},
        )
        if response.status_code >= 300:
            raise SystemExit(f"{action} version {version['id']} failed: {response.status_code} {response.text[:300]}")
        version = response.json()
        print(json.dumps({"action": action, "version": version["id"], "lifecycle_status": version.get("lifecycle_status")}, ensure_ascii=False))
    if version["lifecycle_status"] != "active":
        raise SystemExit(f"version {version['id']} did not reach active: {version['lifecycle_status']}")
    return version


def find_document(session: requests.Session, logical_code: str) -> dict | None:
    documents = _request(session, "GET", f"/projects/{PROJECT_ID}/knowledge/documents").json()
    for document in documents:
        if document.get("logical_code") == logical_code:
            return document
    return None


def ensure_document(session: requests.Session, path: Path, *, knowledge_type: str, source_category: str, logical_code: str, publisher: str, change_note: str) -> dict:
    document = find_document(session, logical_code)
    versions = []
    if document is not None:
        versions = _request(session, "GET", f"/knowledge/documents/{document['id']}/versions", params={"project_id": PROJECT_ID}).json()
    parsed = [
        item for item in versions
        if item.get("parse_status") == "parsed"
        and int(((item.get("parse_summary_json") or {}).get("unit_count")) or 0) > 0
    ]
    if parsed:
        print(json.dumps({"reuse": logical_code, "document_id": document["id"], "version_id": max(parsed, key=lambda item: item["version_no"])["id"]}, ensure_ascii=False))
        return document
    job = upload(session, path, knowledge_type=knowledge_type, source_category=source_category, logical_code=logical_code, publisher=publisher, change_note=change_note)
    document_id = (job.get("result_summary_json") or {}).get("document_id") or job.get("document_id")
    if not document_id:
        raise SystemExit(f"upload job did not report document_id: {json.dumps(job, ensure_ascii=False)[:400]}")
    return {"id": int(document_id)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-reindex", action="store_true")
    args = parser.parse_args()

    fields = load_example_fields()
    content = load_requirement_content()
    scripts = script_rows(content)
    mappings = mapping_rows(content)
    regulatory_path, regulatory_units = build_regulatory_workbook(fields)
    lineage_path, lineage_units = build_lineage_workbook(scripts, mappings)
    rule_path, rule_units = build_rule_workbook(content)
    summary = {
        "example_fields": len(fields),
        "script_rows": len(scripts),
        "mapping_rows": len(mappings),
        "rule_rows": rule_units,
        "regulatory_units_expected": regulatory_units,
        "lineage_units_expected": lineage_units,
        "expected_total_units": regulatory_units + lineage_units + rule_units,
        "files": [str(regulatory_path), str(lineage_path), str(rule_path)],
        "mode": "apply" if args.apply else "dry-run",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        return

    session = _session()
    documents = []
    for path, knowledge_type, source_category, logical_code, publisher, note in (
        (regulatory_path, "field_explanation", "regulatory_formal", "ybt-t51-regulatory-20261026", "一表通监管报送制度（客户示例文档）", "T_5_1 监管口径与字段画像（round 75 检索证据底座）"),
        (lineage_path, "technical_research", "technical_evidence", "ybt-t51-lineage-20261026", "GBASE 跑批脚本与监管集市", "T_5_1 跑批脚本血缘与集市映射（round 75 检索证据底座）"),
        (rule_path, "technical_research", "technical_evidence", "ybt-t51-script-rules-20261026", "GBASE 跑批脚本 YBT_T_5_1.sql", "T_5_1 脚本规则明细（round 75 检索证据底座）"),
    ):
        document = ensure_document(session, path, knowledge_type=knowledge_type, source_category=source_category, logical_code=logical_code, publisher=publisher, change_note=note)
        document_id = document["id"]
        version = activate(session, int(document_id))
        documents.append({
            "document_id": int(document_id),
            "version_id": version["id"],
            "lifecycle_status": version["lifecycle_status"],
            "parse_status": version.get("parse_status"),
            "logical_code": logical_code,
            "file": str(path),
        })
        print(json.dumps(documents[-1], ensure_ascii=False))

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
        print(json.dumps({"reindex": payload if not isinstance(payload, dict) else {k: payload.get(k) for k in ("job_id", "index_version", "already_active", "message")}}, ensure_ascii=False))

    print(json.dumps({"documents": documents, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
