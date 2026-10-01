"""SQL semantic diff: interpretation-level change candidates, never a compliance call."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import AgentStep, AgentTask, Institution, Project, ProjectMembership, User
from app.services.agent.tools.registry import ToolContext, require_tool
from app.services.auth.dependencies import Principal
from app.services.lineage.sql_semantic_diff import CALIBER_AFFECTING, semantic_changes

OLD_SQL = (
    "select sum(deal_amount) as ft_bal\n"
    "from ft_trade_detail\n"
    "where deal_status is not null\n"
)
NEW_SQL = (
    "select sum(deal_amount) as ft_bal\n"
    "from ft_trade_detail\n"
    "where deal_status in ('ACTIVE', 'MATURED')\n"
)
IDENTICAL_SQL = OLD_SQL + "-- 仅注释变化\n"


def test_filter_change_is_reported_as_an_interpretation():
    diff = semantic_changes(OLD_SQL, NEW_SQL)
    assert diff["semantic_changed"] is True
    assert diff["authority"] == "interpretation"
    assert diff["requires_human_confirmation"] is True
    categories = diff["categories"]
    assert categories, "a filter change must produce at least one category"
    assert set(categories) & CALIBER_AFFECTING, categories
    caliber_items = [item for item in diff["items"] if item["affects_caliber"]]
    assert caliber_items
    for item in caliber_items:
        assert item["semantic"] is True
        assert "人工确认" in item["statement"]
        assert "interpretation" in item["statement"]
    assert diff["caliber_affecting_count"] == len(caliber_items)


def test_identical_sql_reports_no_semantic_change():
    diff = semantic_changes(OLD_SQL, IDENTICAL_SQL)
    assert diff["semantic_changed"] is False
    assert diff["categories"] == ["non_semantic"]
    assert diff["semantic_items"] == []
    assert diff["caliber_affecting_count"] == 0


def _context() -> tuple[Session, ToolContext]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    institution = Institution(institution_code="sql-diff-bank", institution_name="SQL 差异验收银行",
                              institution_type="bank", status="active")
    user = User(username="sql_diff_user", display_name="SQL 差异用户", status="active")
    db.add_all([institution, user])
    db.flush()
    project = Project(name="SQL 差异项目", institution_id=institution.id, project_status="active")
    db.add(project)
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=user.id,
                             project_role="project_manager", status="active"))
    task = AgentTask(institution_id=institution.id, project_id=project.id, objective="SQL 语义差异验收",
                     status="running", created_by=user.id, result_summary_json={})
    db.add(task)
    db.flush()
    step = AgentStep(task_id=task.id, plan_id=1, step_key="diff", order_index=1,
                     tool_key="compare_sql_versions", status="running", input_json={})
    db.add(step)
    db.flush()
    principal = Principal(user.id, user.username, user.display_name)
    return db, ToolContext(db=db, principal=principal, project=project, task=task, step=step,
                           tool_input={"old_sql": OLD_SQL, "new_sql": NEW_SQL})


def test_tool_is_registered_as_a_human_gated_high_risk_tool():
    spec = require_tool("compare_sql_versions")
    assert spec.requires_human_confirmation is True
    assert spec.risk_level == "high"
    assert spec.read_only is True
    assert spec.evidence_contract["fact_kinds"] == ["sql_semantic_diff"]
    assert spec.required_permissions == frozenset({"lineage.view"})


def test_tool_emits_only_evidence_linked_interpretation_claims():
    db, context = _context()
    try:
        result = require_tool("compare_sql_versions").handler(context)
        assert result.output["semantic_changed"] is True
        assert result.facts and result.facts[0]["kind"] == "sql_semantic_diff"
        fact_id = result.facts[0]["id"]
        assert result.claims, "each semantic change must become a claim"
        for claim in result.claims:
            assert claim["claim_type"] == "interpretation"
            assert claim["fact_ids"] == [fact_id]
            assert claim["requires_human_confirmation"] is True
            assert not claim["policy_clause_ids"], "an SQL diff is never a policy basis"
        assert result.gaps == []
    finally:
        db.close()


def test_tool_skips_with_a_gap_when_there_is_no_sql_to_compare():
    db, context = _context()
    try:
        context.tool_input = {"old_sql": "   ", "new_sql": NEW_SQL}
        result = require_tool("compare_sql_versions").handler(context)
        assert result.status == "skipped"
        assert result.output["semantic_changed"] is False
        assert [item["code"] for item in result.gaps] == ["sql_baseline_missing"]
    finally:
        db.close()
