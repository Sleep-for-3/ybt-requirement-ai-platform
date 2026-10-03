"""The three business-quality metrics the brief adds to the agent evaluation set."""
from __future__ import annotations

from app.models import (
    AgentPlan,
    AgentHumanDecision,
    AgentStep,
    AgentTask,
    Institution,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import state_machine as sm
from app.services.agent.observability import agent_metrics


def _scope(db):
    institution = Institution(institution_code="metric-bank", institution_name="指标银行",
                              institution_type="bank", status="active")
    user = User(username="metric_manager", display_name="指标管理员", status="active")
    db.add_all([institution, user])
    db.flush()
    project = Project(name="指标项目", institution_id=institution.id, project_status="active")
    db.add(project)
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=user.id,
                             project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_MET", table_name="指标表")
    db.add(table)
    db.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="MT_BAL", field_name="指标余额")
    db.flush()
    return project, user, field


def test_model_execution_and_fallback_rates_follow_the_step_records(db_session):
    project, user, field = _scope(db_session)
    task = AgentTask(institution_id=project.institution_id, project_id=project.id,
                     objective="指标验收：分析指标余额字段", scenario_key="regulatory_field_analysis",
                     status=sm.TASK_COMPLETED, plan_version=1, created_by=user.id)
    db_session.add(task)
    db_session.flush()
    plan = AgentPlan(task_id=task.id, version_no=1, status="active", planner_source="deterministic",
                     objective=task.objective, steps_json=[], created_by=user.id)
    db_session.add(plan)
    db_session.flush()
    db_session.add_all([
        AgentStep(task_id=task.id, plan_id=plan.id, step_key="modelled", tool_key="x", reason="模型步骤",
                  status=sm.STEP_COMPLETED, order_index=1, attempt_count=1,
                  output_summary_json={"model_execution": {"executed": True, "model_name": "deepseek-v4-flash"}}),
        AgentStep(task_id=task.id, plan_id=plan.id, step_key="degraded", tool_key="x", reason="降级步骤",
                  status=sm.STEP_COMPLETED, order_index=2, attempt_count=1,
                  output_summary_json={"model_execution": {"executed": False,
                                                           "degraded_path": "deterministic_draft"}}),
        AgentStep(task_id=task.id, plan_id=plan.id, step_key="plain", tool_key="x", reason="确定性步骤",
                  status=sm.STEP_COMPLETED, order_index=3, attempt_count=1, output_summary_json={}),
    ])
    db_session.flush()
    first_step_id = db_session.query(AgentStep).filter_by(task_id=task.id).order_by(AgentStep.id).first().id
    db_session.add_all([
        AgentHumanDecision(task_id=task.id, step_id=first_step_id, decision=sm.DECISION_APPROVE,
                           context_hash="metric-1", decided_by=user.id),
        AgentHumanDecision(task_id=task.id, step_id=first_step_id,
                           decision=sm.DECISION_REQUEST_REANALYSIS,
                           context_hash="metric-2", decided_by=user.id),
    ])
    db_session.commit()

    metrics = agent_metrics(db_session, project_id=project.id)
    values = metrics["metrics"]
    assert values["model_execution_rate"] == round(1 / 3, 4)
    assert values["deterministic_fallback_rate"] == round(1 / 3, 4)
    assert values["human_reanalysis_rate"] == 0.5
    assert metrics["denominators"]["model_execution_rate"] == 3
    assert metrics["denominators"]["human_reanalysis_rate"] == 2
    assert "model_execution_rate" in metrics["metric_labels"]


def test_metrics_return_null_without_a_denominator(db_session):
    project, _user, _field = _scope(db_session)
    db_session.commit()
    metrics = agent_metrics(db_session, project_id=project.id)
    assert metrics["task_count"] == 0
    assert metrics["metrics"]["model_execution_rate"] is None
    assert metrics["metrics"]["deterministic_fallback_rate"] is None
    assert metrics["metrics"]["human_reanalysis_rate"] is None
