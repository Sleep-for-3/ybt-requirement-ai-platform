from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import BackgroundJob, ProjectMembership, UatCase, UatCaseResult, UatFinding, UatPack, UatPackItem, UatRun, UatSignoff, UatSuite
from app.schemas.uat import EmptyRequest, UatEvidenceAttach, UatFindingCreate, UatFindingResolve, UatFindingUpdate, UatFindingVerify, UatManualResultComplete, UatRunCreate, UatSignoffCreate, UatSuiteCloneRequest, UatSuiteCreate
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.uat import ensure_builtin_uat_suites
from app.services.uat.execution import recalculate_uat_run, uat_run_job_handler
from app.services.uat.packs import create_uat_pack, validate_uat_pack
from app.services.uat.reporting import build_evidence_package, build_uat_report
from app.services.governance.audit import record_audit
from app.services.task_queue import get_task_queue


router = APIRouter(tags=["uat"])


@router.get("/projects/{project_id}/uat-suites")
def list_uat_suites(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    project = PermissionService(db, principal).require_project_permission(project_id, "uat.view")
    ensure_builtin_uat_suites(db, project, principal.user_id)
    suites = db.scalars(select(UatSuite).where(UatSuite.project_id == project_id, UatSuite.enabled.is_(True)).order_by(UatSuite.id)).all()
    return [_suite_detail(db, suite) for suite in suites]


@router.post("/projects/{project_id}/uat-suites", status_code=201)
def create_uat_suite(project_id: int, payload: UatSuiteCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "uat.manage")
    if db.scalar(select(UatSuite.id).where(UatSuite.project_id == project_id, UatSuite.suite_name == payload.suite_name)):
        raise HTTPException(409, "A UAT suite with this name already exists")
    suite = UatSuite(institution_id=project.institution_id, project_id=project.id, suite_name=payload.suite_name, suite_type=payload.suite_type, description=payload.description, enabled=payload.enabled, is_system=False, created_by=principal.user_id)
    db.add(suite); db.flush()
    for item in payload.cases:
        db.add(UatCase(project_id=project.id, uat_suite_id=suite.id, **item.model_dump()))
    record_audit(db, action="create_uat_suite", resource_type="uat_suite", resource_id=suite.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project.id, after={"suite_type": suite.suite_type, "case_count": len(payload.cases)})
    db.commit()
    return _suite_detail(db, suite)


@router.get("/uat-suites/{suite_id}")
def get_uat_suite(suite_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    suite = PermissionService(db, principal).load_project_resource_or_404(UatSuite, suite_id, "uat.view")
    return _suite_detail(db, suite)


@router.post("/uat-suites/{suite_id}/clone", status_code=201)
def clone_uat_suite(suite_id: int, payload: UatSuiteCloneRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    source = PermissionService(db, principal).load_project_resource_or_404(UatSuite, suite_id, "uat.manage")
    clone_name = payload.suite_name or f"{source.suite_name} - 自定义副本"
    if db.scalar(select(UatSuite.id).where(UatSuite.project_id == source.project_id, UatSuite.suite_name == clone_name)):
        raise HTTPException(409, "A UAT suite with this name already exists")
    clone = UatSuite(institution_id=source.institution_id, project_id=source.project_id, suite_name=clone_name, suite_type="custom", description=source.description, enabled=True, is_system=False, created_by=principal.user_id)
    db.add(clone); db.flush()
    for case in db.scalars(select(UatCase).where(UatCase.uat_suite_id == source.id).order_by(UatCase.display_order, UatCase.id)).all():
        db.add(UatCase(project_id=source.project_id, uat_suite_id=clone.id, case_code=case.case_code, case_name=case.case_name, description=case.description, case_category=case.case_category, precondition_json=case.precondition_json, input_requirement_json=case.input_requirement_json, expected_result_json=case.expected_result_json, execution_mode=case.execution_mode, severity=case.severity, enabled=case.enabled, display_order=case.display_order))
    record_audit(db, action="clone_uat_suite", resource_type="uat_suite", resource_id=clone.id, actor_user_id=principal.user_id, institution_id=clone.institution_id, project_id=clone.project_id, after={"source_suite_id": source.id})
    db.commit()
    return _suite_detail(db, clone)


@router.post("/uat-suites/{suite_id}/runs", status_code=201)
def create_uat_run(suite_id: int, payload: UatRunCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    suite = PermissionService(db, principal).load_project_resource_or_404(UatSuite, suite_id, "uat.execute")
    run_no = (db.scalar(select(func.max(UatRun.run_no)).where(UatRun.project_id == suite.project_id, UatRun.uat_suite_id == suite.id)) or 0) + 1
    run = UatRun(institution_id=suite.institution_id, project_id=suite.project_id, uat_suite_id=suite.id, run_name=payload.run_name, run_no=run_no, status="draft", environment_name=payload.environment_name, application_version=payload.application_version, git_commit_sha=payload.git_commit_sha, started_by=principal.user_id, summary_json={"attempt": 0})
    db.add(run); db.flush()
    record_audit(db, action="create_uat_run", resource_type="uat_run", resource_id=run.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"suite_id": suite.id, "run_no": run_no})
    db.commit()
    return _run_detail(db, run)


@router.get("/projects/{project_id}/uat-runs")
def list_uat_runs(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "uat.view")
    return [_run_detail(db, run) for run in db.scalars(select(UatRun).where(UatRun.project_id == project_id).order_by(UatRun.id.desc())).all()]


@router.get("/uat-runs/{run_id}")
def get_uat_run(run_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.view")
    return _run_detail(db, run)


@router.post("/uat-runs/{run_id}/execute")
def execute_run(run_id: int, payload: EmptyRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.execute")
    if run.status not in {"draft", "blocked", "failed"}:
        raise HTTPException(409, "Only draft, blocked or failed UAT runs can be executed")
    return _enqueue_run(db, run, principal.user_id, retry_statuses=None)


@router.post("/uat-runs/{run_id}/retry-failed")
def retry_failed_run(run_id: int, payload: EmptyRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.execute")
    if run.status not in {"failed", "blocked", "cancelled"}:
        raise HTTPException(409, "Only failed, blocked or cancelled UAT runs can be retried")
    return _enqueue_run(db, run, principal.user_id, retry_statuses={"failed", "blocked"})


@router.post("/uat-runs/{run_id}/cancel")
def cancel_uat_run(run_id: int, payload: EmptyRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.execute")
    if run.status not in {"draft", "queued", "running"}:
        raise HTTPException(409, "Only active UAT runs can be cancelled")
    run.status = "cancelled"
    job = db.get(BackgroundJob, run.background_job_id) if run.background_job_id else None
    if job and job.status in {"queued", "running"}:
        get_task_queue().cancel(db, job)
    for result in db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id, UatCaseResult.status.in_(("pending", "running")))).all():
        result.status = "cancelled"
    record_audit(db, action="cancel_uat_run", resource_type="uat_run", resource_id=run.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id)
    db.commit()
    return _run_detail(db, run)


@router.post("/uat-case-results/{result_id}/complete-manual")
def complete_manual_result(result_id: int, payload: UatManualResultComplete, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    result = PermissionService(db, principal).load_project_resource_or_404(UatCaseResult, result_id, "uat.execute")
    case = db.get(UatCase, result.uat_case_id)
    run = db.get(UatRun, result.uat_run_id)
    if case is None or run is None or case.project_id != result.project_id or run.project_id != result.project_id:
        raise HTTPException(404, "UAT case result not found")
    if case.execution_mode not in {"manual", "hybrid"}:
        raise HTTPException(409, "Only manual or hybrid UAT cases can be completed manually")
    if run.status == "cancelled":
        raise HTTPException(409, "Cancelled UAT runs cannot be modified")
    from app.services.governance.audit import redact_summary
    result.status = payload.status; result.actual_result_json = redact_summary(payload.actual_result_json); result.evidence_json = redact_summary(payload.evidence_json); result.error_message = payload.error_message; result.executed_by = principal.user_id; result.executed_at = datetime.now(UTC)
    record_audit(db, action="complete_manual_uat_case", resource_type="uat_case_result", resource_id=result.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"status": result.status})
    db.commit(); recalculate_uat_run(db, run)
    return _row(result)


@router.post("/uat-case-results/{result_id}/attach-evidence")
def attach_result_evidence(result_id: int, payload: UatEvidenceAttach, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    result = PermissionService(db, principal).load_project_resource_or_404(UatCaseResult, result_id, "uat.execute")
    run = db.get(UatRun, result.uat_run_id)
    if run is None or run.project_id != result.project_id:
        raise HTTPException(404, "UAT case result not found")
    from app.services.governance.audit import redact_summary
    result.evidence_json = {**(result.evidence_json or {}), **redact_summary(payload.evidence)}
    record_audit(db, action="attach_uat_evidence", resource_type="uat_case_result", resource_id=result.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"evidence_keys": sorted(result.evidence_json)})
    db.commit()
    return _row(result)


@router.post("/projects/{project_id}/uat-packs/upload", status_code=201)
async def upload_uat_pack(project_id: int, principal: CurrentPrincipal, files: list[UploadFile] = File(...), pack_name: str = Form("脱敏 UAT 材料包"), db: Session = Depends(get_db)) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "uat.manage")
    uploads = [(file.filename or "unnamed", await file.read()) for file in files]
    try:
        pack = create_uat_pack(db, project, pack_name, uploads, principal.user_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    record_audit(db, action="upload_uat_pack", resource_type="uat_pack", resource_id=pack.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project.id, after={"file_count": pack.manifest_json.get("file_count", 0), "total_bytes": pack.manifest_json.get("total_bytes", 0)})
    db.commit()
    return _pack_detail(db, pack)


@router.get("/projects/{project_id}/uat-packs")
def list_uat_packs(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "uat.view")
    return [_pack_detail(db, pack) for pack in db.scalars(select(UatPack).where(UatPack.project_id == project_id).order_by(UatPack.id.desc())).all()]


@router.get("/uat-packs/{pack_id}")
def get_uat_pack(pack_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    pack = PermissionService(db, principal).load_project_resource_or_404(UatPack, pack_id, "uat.view")
    return _pack_detail(db, pack)


@router.post("/uat-packs/{pack_id}/validate")
def validate_pack(pack_id: int, payload: EmptyRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    pack = PermissionService(db, principal).load_project_resource_or_404(UatPack, pack_id, "uat.manage")
    items = list(db.scalars(select(UatPackItem).where(UatPackItem.project_id == pack.project_id, UatPackItem.uat_pack_id == pack.id).order_by(UatPackItem.id)).all())
    result = validate_uat_pack(pack, items)
    record_audit(db, action="validate_uat_pack", resource_type="uat_pack", resource_id=pack.id, actor_user_id=principal.user_id, institution_id=pack.institution_id, project_id=pack.project_id, after={"valid": result["valid"], "missing_material_types": result["missing_material_types"]})
    db.commit()
    return result


@router.post("/uat-runs/{run_id}/findings", status_code=201)
def create_uat_finding(run_id: int, payload: UatFindingCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.finding.manage")
    if payload.uat_case_result_id:
        result = db.get(UatCaseResult, payload.uat_case_result_id)
        if result is None or result.project_id != run.project_id or result.uat_run_id != run.id:
            raise HTTPException(404, "UAT case result not found")
    _validate_assignee(db, run.project_id, payload.assigned_user_id)
    finding_no = (db.scalar(select(func.max(UatFinding.finding_no)).where(UatFinding.uat_run_id == run.id)) or 0) + 1
    finding = UatFinding(institution_id=run.institution_id, project_id=run.project_id, uat_run_id=run.id, finding_no=finding_no, status="assigned" if payload.assigned_user_id or payload.assigned_role else "open", created_by=principal.user_id, **payload.model_dump())
    db.add(finding); db.flush()
    record_audit(db, action="create_uat_finding", resource_type="uat_finding", resource_id=finding.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"finding_no": finding_no, "finding_type": finding.finding_type, "severity": finding.severity})
    db.commit()
    return _row(finding)


@router.get("/uat-runs/{run_id}/findings")
def list_uat_findings(run_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.view")
    return [_row(item) for item in db.scalars(select(UatFinding).where(UatFinding.project_id == run.project_id, UatFinding.uat_run_id == run.id).order_by(UatFinding.finding_no)).all()]


@router.patch("/uat-findings/{finding_id}")
def update_uat_finding(finding_id: int, payload: UatFindingUpdate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    finding = PermissionService(db, principal).load_project_resource_or_404(UatFinding, finding_id, "uat.finding.manage")
    values = payload.model_dump(exclude_unset=True)
    _validate_assignee(db, finding.project_id, values.get("assigned_user_id"))
    for key, value in values.items():
        setattr(finding, key, value)
    record_audit(db, action="update_uat_finding", resource_type="uat_finding", resource_id=finding.id, actor_user_id=principal.user_id, institution_id=finding.institution_id, project_id=finding.project_id, after=values)
    db.commit()
    return _row(finding)


@router.get("/uat-findings/{finding_id}")
def get_uat_finding(finding_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    finding = PermissionService(db, principal).load_project_resource_or_404(UatFinding, finding_id, "uat.view")
    return _row(finding)


@router.post("/uat-findings/{finding_id}/resolve")
def resolve_uat_finding(finding_id: int, payload: UatFindingResolve, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    finding = PermissionService(db, principal).load_project_resource_or_404(UatFinding, finding_id, "uat.finding.manage")
    if finding.status not in {"open", "assigned", "fixing", "rejected"}:
        raise HTTPException(409, "Only an active UAT finding can be resolved")
    finding.status = "resolved"; finding.resolution_text = payload.resolution_text.strip(); finding.resolved_by = principal.user_id; finding.resolved_at = datetime.now(UTC)
    record_audit(db, action="resolve_uat_finding", resource_type="uat_finding", resource_id=finding.id, actor_user_id=principal.user_id, institution_id=finding.institution_id, project_id=finding.project_id, after={"status": finding.status})
    db.commit()
    return _row(finding)


@router.post("/uat-findings/{finding_id}/verify")
def verify_uat_finding(finding_id: int, payload: UatFindingVerify, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    finding = PermissionService(db, principal).load_project_resource_or_404(UatFinding, finding_id, "uat.finding.manage")
    if finding.status != "resolved":
        raise HTTPException(409, "Only a resolved UAT finding can be verified")
    finding.status = "verified"; finding.verified_by = principal.user_id; finding.verified_at = datetime.now(UTC)
    record_audit(db, action="verify_uat_finding", resource_type="uat_finding", resource_id=finding.id, actor_user_id=principal.user_id, institution_id=finding.institution_id, project_id=finding.project_id, after={"status": finding.status, "verification_comment": payload.verification_comment})
    db.commit()
    return _row(finding)


@router.post("/uat-runs/{run_id}/signoff", status_code=201)
def create_uat_signoff(run_id: int, payload: UatSignoffCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    permissions = PermissionService(db, principal)
    run = permissions.load_project_resource_or_404(UatRun, run_id, "uat.signoff")
    permissions.require_uat_signoff_role(run.project_id, payload.signoff_role)
    if run.status != "passed":
        raise HTTPException(409, "Only a completed and passed UAT run can be signed off")
    blocking = db.scalar(select(UatFinding.id).where(UatFinding.project_id == run.project_id, UatFinding.uat_run_id == run.id, UatFinding.severity == "critical", UatFinding.status.not_in(("verified", "rejected", "closed"))).limit(1))
    if blocking is not None:
        raise HTTPException(409, "Critical UAT findings must be verified or closed before signoff")
    signoff = UatSignoff(project_id=run.project_id, uat_run_id=run.id, signoff_role=payload.signoff_role, signoff_status=payload.signoff_status, comment=payload.comment, signed_by=principal.user_id, signed_at=datetime.now(UTC))
    db.add(signoff); db.flush()
    record_audit(db, action="signoff_uat_run", resource_type="uat_signoff", resource_id=signoff.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"signoff_role": signoff.signoff_role, "signoff_status": signoff.signoff_status})
    db.commit()
    return _row(signoff)


@router.get("/uat-runs/{run_id}/signoffs")
def list_uat_signoffs(run_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.view")
    return [_row(item) for item in db.scalars(select(UatSignoff).where(UatSignoff.project_id == run.project_id, UatSignoff.uat_run_id == run.id).order_by(UatSignoff.id)).all()]


@router.get("/uat-runs/{run_id}/report")
def download_uat_report(run_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.view")
    content = build_uat_report(db, run)
    record_audit(db, action="download_uat_report", resource_type="uat_run", resource_id=run.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"byte_size": len(content)})
    db.commit()
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=uat-report-{run.id}.xlsx"})


@router.get("/uat-runs/{run_id}/evidence-package")
def download_uat_evidence(run_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    run = PermissionService(db, principal).load_project_resource_or_404(UatRun, run_id, "uat.view")
    content = build_evidence_package(db, run)
    record_audit(db, action="download_uat_evidence_package", resource_type="uat_run", resource_id=run.id, actor_user_id=principal.user_id, institution_id=run.institution_id, project_id=run.project_id, after={"byte_size": len(content)})
    db.commit()
    return Response(content, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=uat-evidence-{run.id}.zip"})


def _suite_detail(db: Session, suite: UatSuite) -> dict:
    cases = db.scalars(select(UatCase).where(UatCase.uat_suite_id == suite.id, UatCase.enabled.is_(True)).order_by(UatCase.display_order, UatCase.id)).all()
    return {"id": suite.id, "institution_id": suite.institution_id, "project_id": suite.project_id, "suite_name": suite.suite_name, "suite_type": suite.suite_type, "description": suite.description, "enabled": suite.enabled, "is_system": suite.is_system, "cases": [{"id": case.id, "project_id": case.project_id, "uat_suite_id": case.uat_suite_id, "case_code": case.case_code, "case_name": case.case_name, "description": case.description, "case_category": case.case_category, "precondition_json": case.precondition_json, "input_requirement_json": case.input_requirement_json, "expected_result_json": case.expected_result_json, "execution_mode": case.execution_mode, "severity": case.severity, "enabled": case.enabled, "display_order": case.display_order} for case in cases]}


def _enqueue_run(db: Session, run: UatRun, started_by: int | None, retry_statuses: set[str] | None) -> dict:
    attempt = int((run.summary_json or {}).get("attempt", 0)) + 1
    run.summary_json = {**(run.summary_json or {}), "attempt": attempt}
    run.status = "queued"
    db.commit()
    job = get_task_queue().enqueue(db, job_type="uat_run_execute", institution_id=run.institution_id, project_id=run.project_id, created_by=started_by or 0, idempotency_key=f"uat-run:{run.id}:attempt:{attempt}", payload_summary={"uat_run_id": run.id, "retry_statuses": sorted(retry_statuses or [])}, handler=uat_run_job_handler)
    run = db.get(UatRun, run.id)
    run.background_job_id = job.id
    db.commit()
    return {"run": _run_detail(db, run), "job": _row(job)}


def _run_detail(db: Session, run: UatRun) -> dict:
    cases = {case.id: case for case in db.scalars(select(UatCase).where(UatCase.uat_suite_id == run.uat_suite_id)).all()}
    results = list(db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id).order_by(UatCaseResult.id)).all())
    return {**_row(run), "results": [{**_row(result), "case": _row(cases[result.uat_case_id])} for result in results]}


def _pack_detail(db: Session, pack: UatPack) -> dict:
    items = list(db.scalars(select(UatPackItem).where(UatPackItem.project_id == pack.project_id, UatPackItem.uat_pack_id == pack.id).order_by(UatPackItem.id)).all())
    return {**_row(pack), "items": [_row(item) for item in items]}


def _row(item) -> dict:
    return {attribute.key: getattr(item, attribute.key) for attribute in inspect(item).mapper.column_attrs}


def _validate_assignee(db: Session, project_id: int, user_id: int | None) -> None:
    if user_id is None:
        return
    membership = db.scalar(select(ProjectMembership.id).where(ProjectMembership.project_id == project_id, ProjectMembership.user_id == user_id, ProjectMembership.status == "active"))
    if membership is None:
        raise HTTPException(400, "Assigned user is not an active project member")
