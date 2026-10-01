"""SQL change event agent: detect a semantic change and open one governed task.

Whitespace, comments and formatting must never trigger an analysis, so detection is
based on a **semantic hash** derived from the parsed lineage of the version (source →
target plus filter/join/aggregation/code-mapping attributes), not on the raw text.

``sql_change_events`` is the idempotency anchor: the same (project, script, old
version, new version, semantic hash) can never produce a second agent task, even when
the same version is imported repeatedly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AgentTask, Project, ScriptFile, ScriptFileVersion, SqlChangeEvent, SqlStatement
from app.services.agent import runtime
from app.services.auth.dependencies import Principal
from app.services.lineage.sql_parser import parse_sql_lineage
from app.services.lineage.sql_semantic_diff import semantic_changes
from app.services.llm.execution_metadata import stable_hash

SCENARIO_SQL_CHANGE_IMPACT = "sql_change_impact"
EVENT_DETECTED = "detected"
EVENT_TASK_CREATED = "task_created"
EVENT_TASK_FAILED = "task_failed"


@dataclass(frozen=True)
class DetectedChange:
    script_file_id: int
    script_name: str
    old_version_id: int | None
    old_version_no: int | None
    new_version_id: int
    new_version_no: int
    semantic_hash: str
    old_semantic_hash: str | None
    severity: str
    categories: list[str]
    diff: dict[str, Any]
    objective: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "script_file_id": self.script_file_id, "script_name": self.script_name,
            "old_version_id": self.old_version_id, "old_version_no": self.old_version_no,
            "new_version_id": self.new_version_id, "new_version_no": self.new_version_no,
            "semantic_hash": self.semantic_hash, "old_semantic_hash": self.old_semantic_hash,
            "severity": self.severity, "categories": self.categories,
            "objective": self.objective,
        }


def semantic_hash(sql_text: str, *, dialect: str = "") -> str:
    """Hash the parsed semantic content only (never the raw text)."""

    parsed = parse_sql_lineage(sql_text or "", dialect=dialect)
    edges = sorted(
        (
            (edge.source.node_type, edge.source.logical_name, edge.target.node_type, edge.target.logical_name,
             edge.edge_type, edge.transformation_type or "", edge.filter_condition or "",
             edge.join_condition or "", edge.aggregation_rule or "", edge.code_mapping_rule or "")
            for edge in parsed.edges
        ),
        key=lambda item: tuple(str(part) for part in item),
    )
    return stable_hash({"edges": edges})[:64]


def version_sql(db, version: ScriptFileVersion | None) -> str:
    if version is None:
        return ""
    statements = list(db.scalars(select(SqlStatement).where(
        SqlStatement.script_file_version_id == version.id).order_by(SqlStatement.statement_index)).all())
    return "\n".join(statement.normalized_sql or "" for statement in statements)


def detect_sql_change(db, *, script_file_id: int, new_version_id: int | None = None) -> DetectedChange | None:
    """Return the semantic change of a script's newest version, or None when there is none."""

    script = db.get(ScriptFile, script_file_id)
    if script is None:
        return None
    versions = list(db.scalars(select(ScriptFileVersion)
                               .where(ScriptFileVersion.script_file_id == script.id)
                               .order_by(ScriptFileVersion.version_no)).all())
    if not versions:
        return None
    new_version = next((item for item in versions if item.id == new_version_id), None) or versions[-1]
    previous = next((item for item in reversed(versions) if item.version_no < new_version.version_no), None)
    new_sql = version_sql(db, new_version)
    old_sql = version_sql(db, previous)
    new_hash = semantic_hash(new_sql, dialect=new_version.dialect or "")
    old_hash = semantic_hash(old_sql, dialect=previous.dialect or "") if previous is not None else None
    if previous is not None and new_hash == old_hash:
        return None  # formatting/comment-only change: no analysis, no task
    if previous is None and not new_sql.strip():
        return None
    diff = semantic_changes(old_sql, new_sql, dialect=new_version.dialect or "")
    if previous is not None and not diff["semantic_changed"]:
        return None
    objective = (f"分析脚本 {script.file_name} 从版本 "
                 f"{previous.version_no if previous else '初始'} 到版本 {new_version.version_no} "
                 "的语义变化及其对监管口径的影响。")
    return DetectedChange(
        script_file_id=script.id, script_name=script.file_name,
        old_version_id=previous.id if previous else None,
        old_version_no=previous.version_no if previous else None,
        new_version_id=new_version.id, new_version_no=new_version.version_no,
        semantic_hash=new_hash, old_semantic_hash=old_hash,
        severity=str(diff.get("severity") or "low"),
        categories=list(diff.get("categories") or []),
        diff=diff, objective=objective,
    )


def trigger_sql_change_agent(
    db, project: Project, principal: Principal, *, script_file_id: int, new_version_id: int | None = None,
    auto_start: bool = True, adaptive: bool = True,
) -> dict[str, Any]:
    """Detect a semantic change and open exactly one agent task for it."""

    change = detect_sql_change(db, script_file_id=script_file_id, new_version_id=new_version_id)
    if change is None:
        return {"triggered": False, "reason": "no_semantic_change"}
    existing = db.scalar(select(SqlChangeEvent).where(
        SqlChangeEvent.project_id == project.id,
        SqlChangeEvent.script_file_id == change.script_file_id,
        SqlChangeEvent.old_version_id == change.old_version_id,
        SqlChangeEvent.new_version_id == change.new_version_id,
        SqlChangeEvent.semantic_hash == change.semantic_hash,
    ))
    if existing is not None:
        return {"triggered": False, "reason": "duplicate_event", "event_id": existing.id,
                "agent_task_id": existing.agent_task_id, "status": existing.status}

    event = SqlChangeEvent(
        institution_id=project.institution_id, project_id=project.id,
        script_file_id=change.script_file_id, old_version_id=change.old_version_id,
        new_version_id=change.new_version_id, semantic_hash=change.semantic_hash,
        old_semantic_hash=change.old_semantic_hash, severity=change.severity,
        categories_json=change.categories,
        diff_summary_json={"categories": change.categories, "severity": change.severity,
                           "caliber_affecting_count": change.diff.get("caliber_affecting_count"),
                           "unsupported_families": change.diff.get("unsupported_families")},
        change_note=f"版本 {change.old_version_no} → {change.new_version_no}",
        status=EVENT_DETECTED, detected_by=int(principal.user_id or 0),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:  # a concurrent trigger won the race: reuse its event
        db.rollback()
        existing = db.scalar(select(SqlChangeEvent).where(
            SqlChangeEvent.project_id == project.id,
            SqlChangeEvent.script_file_id == change.script_file_id,
            SqlChangeEvent.new_version_id == change.new_version_id,
            SqlChangeEvent.semantic_hash == change.semantic_hash,
        ))
        return {"triggered": False, "reason": "duplicate_event",
                "event_id": existing.id if existing else None,
                "agent_task_id": existing.agent_task_id if existing else None}

    try:
        task = _create_task_for_event(db, project, principal, change, event, adaptive=adaptive, auto_start=auto_start)
    except Exception as exc:  # noqa: BLE001 - the event stays for retry, ingestion never breaks
        db.rollback()
        event = db.get(SqlChangeEvent, event.id) if event.id else None
        if event is not None:
            event.status = EVENT_TASK_FAILED
            event.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            db.commit()
        return {"triggered": False, "reason": "task_creation_failed", "error": type(exc).__name__}
    event.status = EVENT_TASK_CREATED
    event.agent_task_id = task.id
    db.commit()
    return {"triggered": True, "event_id": event.id, "agent_task_id": task.id,
            "scenario_key": SCENARIO_SQL_CHANGE_IMPACT, "objective": change.objective,
            "categories": change.categories, "severity": change.severity,
            "auto_started": bool(auto_start)}


def _create_task_for_event(db, project: Project, principal: Principal, change: DetectedChange,
                           event: SqlChangeEvent, *, adaptive: bool, auto_start: bool) -> AgentTask:
    task = runtime.create_task(
        db, principal, project, change.objective,
        scenario_key=SCENARIO_SQL_CHANGE_IMPACT, use_llm_planner=True, adaptive=adaptive,
    )
    summary = dict(task.result_summary_json or {})
    summary["change_context"] = {
        **change.as_dict(),
        "event_id": event.id,
        "semantic_diff_ref": f"sql_diff:{change.semantic_hash}",
    }
    task.result_summary_json = summary
    db.commit()
    if auto_start:
        job = runtime.submit_task(db, project, principal, task)
        task.background_job_id = job.id
        db.commit()
    return task


def semantic_change_summary(diff: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """Compact rendering of the semantic changes for an impact artifact or the UI."""

    items = diff.get("items") or diff.get("facts") or []
    return [
        {"category": item.get("category"), "before": item.get("before"), "after": item.get("after"),
         "severity": item.get("severity"), "affects_caliber": bool(item.get("affects_caliber"))}
        for item in items[:limit]
    ]
