"""SQL change event agent: semantic-hash detection, one task per change, dedup on repeat."""
from __future__ import annotations

import pytest

from app.models import (
    AgentPlan,
    AgentTask,
    Institution,
    Project,
    ProjectMembership,
    ScriptFile,
    ScriptFileVersion,
    SqlChangeEvent,
    SqlStatement,
    StoredFile,
    User,
)
from app.services.agent import runtime, sql_change_events as events
from app.services.auth.dependencies import Principal

BEFORE = ("insert into ybt_ft (bal)\n"
          "select sum(deal_amount) from ft_trade_detail\n"
          "where deal_status is not null;")
AFTER_PREDICATE = ("insert into ybt_ft (bal)\n"
                   "select sum(deal_amount) from ft_trade_detail\n"
                   "where deal_status in ('ACTIVE', 'MATURED');")
AFTER_FORMAT_ONLY = ("-- 只是格式与注释变化\n"
                     "insert into ybt_ft (bal)\n"
                     "  select sum(deal_amount)\n"
                     "  from ft_trade_detail\n"
                     "  where deal_status is not null;")


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="evt-bank", institution_name="变更事件银行",
                              institution_type="bank", status="active")
    user = User(username="evt_manager", display_name="变更事件管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="变更事件项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    db_session.commit()
    return {"db": db_session, "project": project, "user": user,
            "principal": Principal(user.id, user.username, user.display_name)}


def _script(db, project, *, versions: list[str], file_name: str = "ft_bal.sql") -> ScriptFile:
    script = ScriptFile(project_id=project.id, file_name=file_name, relative_path=f"scripts/{file_name}",
                        file_type="sql", current_version_no=len(versions))
    db.add(script)
    db.flush()
    for index, sql in enumerate(versions, start=1):
        stored = StoredFile(institution_id=project.institution_id, project_id=project.id,
                            storage_key=f"mem/{file_name}.v{index}",
                            original_file_name=f"{file_name}.v{index}", content_type="text/plain",
                            byte_size=len(sql), content_hash=f"c{index}", created_by=1)
        db.add(stored)
        db.flush()
        version = ScriptFileVersion(project_id=project.id, script_file_id=script.id, version_no=index,
                                    raw_content_storage_file_id=stored.id, parse_status="parsed",
                                    dialect="", file_hash=f"f{index}", normalized_hash=f"h{index}",
                                    warnings_json=[], created_by=1)
        db.add(version)
        db.flush()
        db.add(SqlStatement(project_id=project.id, script_file_version_id=version.id,
                            statement_index=1, statement_type="insert", raw_sql_hash=f"r{index}",
                            normalized_sql=sql, parse_status="parsed", warnings_json=[]))
    db.commit()
    return script


def test_semantic_hash_ignores_formatting_and_comments():
    assert events.semantic_hash(BEFORE) == events.semantic_hash(AFTER_FORMAT_ONLY)
    assert events.semantic_hash(BEFORE) != events.semantic_hash(AFTER_PREDICATE)


def test_a_format_only_change_detects_nothing(scope):
    db, project = scope["db"], scope["project"]
    script = _script(db, project, versions=[BEFORE, AFTER_FORMAT_ONLY])
    assert events.detect_sql_change(db, script_file_id=script.id) is None
    assert events.trigger_sql_change_agent(db, project, scope["principal"],
                                          script_file_id=script.id) == {"triggered": False,
                                                                        "reason": "no_semantic_change"}
    assert db.query(SqlChangeEvent).count() == 0
    assert db.query(AgentTask).count() == 0


def test_a_semantic_change_creates_one_task_and_dedups_on_repeat(scope):
    db, project = scope["db"], scope["project"]
    script = _script(db, project, versions=[BEFORE, AFTER_PREDICATE])

    first = events.trigger_sql_change_agent(db, project, scope["principal"], script_file_id=script.id,
                                           auto_start=False)
    assert first["triggered"] is True
    assert first["scenario_key"] == "sql_change_impact"
    assert "初始" in first["objective"] or "版本 1" in first["objective"]
    assert "filter_changed" in first["categories"]

    task = db.get(AgentTask, first["agent_task_id"])
    assert task.scenario_key == "sql_change_impact"
    context = (task.result_summary_json or {})["change_context"]
    assert context["script_file_id"] == script.id
    assert context["new_version_no"] == 2 and context["old_version_no"] == 1
    assert context["semantic_hash"] == events.semantic_hash(AFTER_PREDICATE)
    assert context["semantic_diff_ref"].startswith("sql_diff:")
    plan = db.query(AgentPlan).filter_by(task_id=task.id).order_by(AgentPlan.version_no).first()
    assert plan is not None, "the change task must carry a materialized plan"

    # Re-importing the very same change must not create a second task.
    again = events.trigger_sql_change_agent(db, project, scope["principal"], script_file_id=script.id,
                                            auto_start=False)
    assert again["triggered"] is False and again["reason"] == "duplicate_event"
    assert again["agent_task_id"] == task.id
    assert db.query(AgentTask).count() == 1
    assert db.query(SqlChangeEvent).count() == 1


def test_the_event_records_the_diff_and_the_actor(scope):
    db, project = scope["db"], scope["project"]
    script = _script(db, project, versions=[BEFORE, AFTER_PREDICATE], file_name="loan_bal.sql")
    events.trigger_sql_change_agent(db, project, scope["principal"], script_file_id=script.id, auto_start=False)
    event = db.query(SqlChangeEvent).one()
    assert event.status == events.EVENT_TASK_CREATED
    assert event.detected_by == scope["user"].id
    assert event.agent_task_id is not None
    assert event.diff_summary_json["categories"]
    assert event.change_note and "→" in event.change_note
    assert event.script_file_id == script.id


def test_change_summary_is_ui_ready(scope):
    db, project = scope["db"], scope["project"]
    script = _script(db, project, versions=[BEFORE, AFTER_PREDICATE])
    change = events.detect_sql_change(db, script_file_id=script.id)
    summary = events.semantic_change_summary(change.diff)
    assert summary
    assert {"category", "before", "after", "severity", "affects_caliber"} == set(summary[0])
    assert any(item["affects_caliber"] for item in summary), "a predicate narrowing affects the caliber"


def test_missing_script_is_a_noop(scope):
    assert events.detect_sql_change(scope["db"], script_file_id=99999) is None
    assert events.trigger_sql_change_agent(scope["db"], scope["project"], scope["principal"],
                                          script_file_id=99999)["reason"] == "no_semantic_change"
