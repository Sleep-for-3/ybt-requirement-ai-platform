from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
import json
import zipfile

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import DeliverablePackageVersion, StoredFile, UatCase, UatCaseResult, UatFinding, UatRun, UatSignoff, UatSuite
from app.services.deployment import database_revisions
from app.services.governance.audit import redact_summary
from app.services.health_checks import run_health_checks


SHEET_NAMES = ["验收概览", "测试套件", "测试案例", "失败案例", "阻断案例", "问题清单", "修复记录", "签署记录", "环境信息", "版本信息"]


def build_uat_report(db: Session, run: UatRun) -> bytes:
    suite = db.get(UatSuite, run.uat_suite_id)
    cases = {item.id: item for item in db.scalars(select(UatCase).where(UatCase.uat_suite_id == suite.id)).all()}
    results = list(db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id).order_by(UatCaseResult.id)).all())
    findings = list(db.scalars(select(UatFinding).where(UatFinding.uat_run_id == run.id).order_by(UatFinding.finding_no)).all())
    signoffs = list(db.scalars(select(UatSignoff).where(UatSignoff.uat_run_id == run.id).order_by(UatSignoff.id)).all())
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name in SHEET_NAMES:
        workbook.create_sheet(name)
    _append_rows(workbook["验收概览"], ["项目ID", "Run ID", "名称", "状态", "总数", "通过", "失败", "阻断", "待处理"], [[run.project_id, run.id, run.run_name, run.status, len(results), _count(results, "passed"), _count(results, "failed"), _count(results, "blocked"), _count(results, "pending")]])
    _append_rows(workbook["测试套件"], ["套件ID", "名称", "类型", "说明"], [[suite.id, suite.suite_name, suite.suite_type, suite.description]])
    case_rows = [[case.case_code, case.case_name, case.execution_mode, case.severity, result.status, result.duration_ms, _json(result.expected_result_json), _json(result.actual_result_json), _json(result.evidence_json)] for result in results for case in [cases[result.uat_case_id]]]
    headers = ["Case 编码", "Case 名称", "执行模式", "严重度", "状态", "耗时毫秒", "预期结果", "实际结果", "证据"]
    _append_rows(workbook["测试案例"], headers, case_rows)
    _append_rows(workbook["失败案例"], headers, [row for row in case_rows if row[4] == "failed"])
    _append_rows(workbook["阻断案例"], headers, [row for row in case_rows if row[4] == "blocked"])
    finding_headers = ["问题编号", "类型", "严重度", "标题", "状态", "指派角色", "说明"]
    _append_rows(workbook["问题清单"], finding_headers, [[item.finding_no, item.finding_type, item.severity, item.title, item.status, item.assigned_role, item.description] for item in findings])
    _append_rows(workbook["修复记录"], ["问题编号", "状态", "解决说明", "解决时间", "验证时间"], [[item.finding_no, item.status, item.resolution_text, item.resolved_at, item.verified_at] for item in findings])
    _append_rows(workbook["签署记录"], ["角色", "状态", "意见", "签署人ID", "签署时间"], [[item.signoff_role, item.signoff_status, item.comment, item.signed_by, item.signed_at] for item in signoffs])
    _append_rows(workbook["环境信息"], ["环境", "应用版本", "开始时间", "完成时间"], [[run.environment_name, run.application_version, run.started_at, run.completed_at]])
    _append_rows(workbook["版本信息"], ["Git Commit SHA", "Run No", "报告生成日期"], [[run.git_commit_sha, run.run_no, date.today().isoformat()]])
    stream = BytesIO(); workbook.save(stream); return stream.getvalue()


def build_evidence_package(db: Session, run: UatRun) -> bytes:
    report = build_uat_report(db, run)
    results = list(db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id).order_by(UatCaseResult.id)).all())
    delivery_files = [{
        "package_version_id": version.id,
        "deliverable_package_id": version.deliverable_package_id,
        "version_no": version.version_no,
        "stored_file_id": stored.id,
        "file_name": stored.original_file_name,
        "byte_size": stored.byte_size,
        "content_hash": stored.content_hash,
    } for version, stored in db.execute(
        select(DeliverablePackageVersion, StoredFile)
        .join(StoredFile, StoredFile.id == DeliverablePackageVersion.generated_file_id)
        .where(DeliverablePackageVersion.project_id == run.project_id)
        .order_by(DeliverablePackageVersion.id)
    )]
    current_revision, head_revision = database_revisions(db.connection())
    entries = {
        "uat-report.xlsx": report,
        "case-results.json": _json_bytes([{"case_result_id": item.id, "case_id": item.uat_case_id, "status": item.status, "actual_result": item.actual_result_json, "evidence": item.evidence_json, "duration_ms": item.duration_ms} for item in results]),
        "health-summary.json": _safe_json_bytes(run_health_checks(db, get_settings())),
        "delivery-file-references.json": _safe_json_bytes({"references": delivery_files, "restricted_files_included": False}),
        "version.json": _safe_json_bytes({"alembic_revision": current_revision, "alembic_head_revision": head_revision, "git_commit_sha": run.git_commit_sha, "application_version": run.application_version}),
    }
    checksums = "".join(f"{sha256(content).hexdigest()}  {name}\n" for name, content in sorted(entries.items())).encode()
    entries["SHA256SUMS"] = checksums
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 22, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return stream.getvalue()


def _append_rows(sheet, headers: list[str], rows: list[list]) -> None:
    sheet.append([_safe_excel_value(value) for value in headers])
    for row in rows:
        sheet.append([_safe_excel_value(value) for value in row])
    sheet.freeze_panes = "A2"


def _safe_excel_value(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _count(results: list[UatCaseResult], status: str) -> int:
    return sum(item.status == status for item in results)


def _json(value) -> str:
    return json.dumps(redact_summary(value), ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_bytes(value) -> bytes:
    return _json(value).encode("utf-8")


def _safe_json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default).encode("utf-8")


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
