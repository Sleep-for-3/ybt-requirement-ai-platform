from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, UatCase, UatCaseResult, UatRun
from app.services.governance.audit import record_audit, redact_summary
from app.services.governance.notifications import notify_user


def execute_uat_run(db: Session, run_id: int, *, retry_statuses: set[str] | None = None) -> dict:
    """Execute an ordered UAT run while persisting each case as an independent checkpoint."""
    run = db.get(UatRun, run_id)
    if run is None:
        raise ValueError("UAT run not found")
    cases = list(db.scalars(select(UatCase).where(UatCase.uat_suite_id == run.uat_suite_id, UatCase.enabled.is_(True)).order_by(UatCase.display_order, UatCase.id)).all())
    results = _ensure_results(db, run, cases)
    run.status = "running"
    run.started_at = run.started_at or datetime.now(UTC)
    db.commit()
    by_code = {case.case_code: results[case.id] for case in cases}
    for case in cases:
        db.refresh(run)
        result = results[case.id]
        if run.status == "cancelled":
            break
        if retry_statuses is not None and result.status not in retry_statuses:
            continue
        if retry_statuses is None and result.status in {"passed", "skipped", "cancelled"}:
            continue
        dependencies = [str(item) for item in case.precondition_json.get("depends_on", [])]
        blocked_by = [code for code in dependencies if code in by_code and by_code[code].status in {"failed", "blocked", "cancelled"}]
        if blocked_by:
            _finish_result(db, result, "blocked", {"blocked_by": blocked_by}, {}, None, 0, run.started_by)
            continue
        if case.execution_mode == "manual":
            _finish_result(db, result, "pending", {"manual_confirmation_required": True}, {}, None, 0, None)
            continue
        started = perf_counter()
        result.status = "running"
        db.commit()
        try:
            outcome = _evaluate_case(case)
            duration_ms = max(0, int((perf_counter() - started) * 1000))
            if case.execution_mode == "hybrid" and outcome["status"] == "passed":
                _finish_result(db, result, "pending", {**outcome["actual"], "manual_confirmation_required": True}, outcome["evidence"], None, duration_ms, run.started_by)
            else:
                _finish_result(db, result, outcome["status"], outcome["actual"], outcome["evidence"], outcome.get("error"), duration_ms, run.started_by)
        except Exception as exc:
            duration_ms = max(0, int((perf_counter() - started) * 1000))
            _finish_result(db, result, "failed", {}, {}, str(redact_summary(str(exc)))[:1000], duration_ms, run.started_by)
    return _finalize_run(db, run, list(results.values()))


def uat_run_job_handler(db: Session, job: BackgroundJob) -> dict:
    run_id = int(job.payload_summary_json["uat_run_id"])
    retry_statuses = set(job.payload_summary_json.get("retry_statuses") or []) or None
    summary = execute_uat_run(db, run_id, retry_statuses=retry_statuses)
    run = db.get(UatRun, run_id)
    record_audit(db, action="execute_uat_run", resource_type="uat_run", resource_id=run_id, actor_user_id=job.created_by, institution_id=job.institution_id, project_id=job.project_id, after={"background_job_id": job.id, "summary": summary})
    notify_user(db, job.created_by, "uat_run_completed", "UAT 执行完成", f"UAT Run {run_id} 状态：{run.status}", project_id=run.project_id, resource_type="uat_run", resource_id=run.id)
    db.commit()
    return {"success_count": summary["passed_count"], "failed_count": summary["failed_count"], "blocked_count": summary["blocked_count"], "pending_count": summary["pending_count"], "uat_run_id": run_id, "run_status": run.status}


def recalculate_uat_run(db: Session, run: UatRun) -> dict:
    results = list(db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id)).all())
    return _finalize_run(db, run, results)


def _ensure_results(db: Session, run: UatRun, cases: list[UatCase]) -> dict[int, UatCaseResult]:
    results = {item.uat_case_id: item for item in db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id)).all()}
    for case in cases:
        if case.id not in results:
            result = UatCaseResult(project_id=run.project_id, uat_run_id=run.id, uat_case_id=case.id, status="pending", expected_result_json=case.expected_result_json, actual_result_json={}, evidence_json={})
            db.add(result); db.flush(); results[case.id] = result
    db.commit()
    return results


def _evaluate_case(case: UatCase) -> dict:
    check_key = str(case.precondition_json.get("check_key") or "")
    if check_key == "always_fail":
        return {"status": "failed", "actual": {"check": "controlled_failure"}, "evidence": {"check_key": check_key}, "error": "Controlled sanitized UAT failure"}
    if check_key == "always_pass":
        return {"status": "passed", "actual": {"check": "passed"}, "evidence": {"check_key": check_key}}
    return {"status": "blocked", "actual": {"check": "manual_or_environment_evidence_required"}, "evidence": {"check_key": check_key}}


def _finish_result(db: Session, result: UatCaseResult, status: str, actual: dict, evidence: dict, error: str | None, duration_ms: int, executed_by: int | None) -> None:
    result.status = status
    result.actual_result_json = redact_summary(actual)
    result.evidence_json = redact_summary(evidence)
    result.error_message = error
    result.duration_ms = duration_ms
    result.executed_by = executed_by
    result.executed_at = datetime.now(UTC) if status != "pending" else None
    db.commit()


def _finalize_run(db: Session, run: UatRun, results: list[UatCaseResult]) -> dict:
    counts = {status: sum(item.status == status for item in results) for status in ("passed", "failed", "blocked", "pending", "skipped", "cancelled")}
    if run.status != "cancelled":
        run.status = "failed" if counts["failed"] else "blocked" if counts["blocked"] or counts["pending"] else "passed"
    run.completed_at = datetime.now(UTC) if run.status in {"passed", "failed", "blocked", "cancelled"} else None
    attempt = int((run.summary_json or {}).get("attempt", 1))
    summary = {"total_count": len(results), **{f"{key}_count": value for key, value in counts.items()}, "attempt": attempt}
    run.summary_json = summary
    db.commit()
    return summary
