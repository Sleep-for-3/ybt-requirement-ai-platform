"""VNext2 P1-A：Agent 五类业务决策的执行证据（真实运行时 + 真实工具注册表）。

本文件覆盖任务书第六章要求的五类决策在**运行时层**的可复现证据：

1. 信息充分：真实工具（元数据检索/字段召回/证据汇总）被编排执行，形成候选，
   但绝不自动写入已确认口径或映射（停在人工采用之前）。
2. 缺少输入：需求候选项在缺少需求生成输入时**阻断**，并给出下一步动作，
   而不是输出一份看起来完成的确定性草稿。
3. Skill 未绑定：字段重排没有固定采用的已发布版本时，走标注过的确定性回退，
   并显式给出绑定待办；系统不得自动绑定最新发布版。
4. 需要人工确认：冲突在第一处人工门控停下，已完成证据保留；人工通过后继续执行完成。
5. 人工否决：被否决的步骤不得通过「重试」静默重跑并重新采纳同一结论；
   只能走有边界的重规划（replan）。

工具层面的等价证据已存在于 ``tests/test_agent_ai_skill_tools.py``（阻断 + 下一步动作），
本文件补齐运行时的状态机、证据保留与拒绝语义。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import (
    AgentPlan,
    AgentStep,
    AgentTask,
    AISkillScopeBinding,
    CatalogColumn,
    CatalogSchema,
    CatalogTable,
    DataSource,
    Institution,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    key = f"{tool_key}_{_SEQ['n']}"
    values = dict(
        display_name=tool_key,
        description=f"P1-A 决策工具 {tool_key}",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}),
        risk_level="low",
        timeout_seconds=5,
        retry_policy={"max_attempts": 1},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []},
        audit_fields=(),
        handler=handler,
    )
    values.update(overrides)
    register_tool(AgentToolSpec(tool_key=key, **values))
    return key


@pytest.fixture()
def scope(db_session):
    """隔离项目：目标字段 + 可被真实召回匹配的目录元数据。"""
    institution = Institution(
        institution_code="dec-bank", institution_name="决策银行", institution_type="bank", status="active",
    )
    user = User(username="dec_manager", display_name="决策管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(
        name="P1-A 决策项目", institution_id=institution.id, project_status="active",
        bank_name="决策银行", description="Agent 五类业务决策验收",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(
        project_id=project.id, user_id=user.id, project_role="project_manager", status="active",
    ))
    table = TargetTable(project_id=project.id, table_code="YBT_DEC", table_name="决策目标表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(
        project_id=project.id, target_table_id=table.id,
        field_code="CUST_BAL", field_name="客户存款余额", field_definition="客户在本行的存款余额",
    )
    db_session.add(field)
    db_session.flush()

    datasource = DataSource(
        project_id=project.id, name="CORE", display_name="核心系统", db_type="gbase",
    )
    db_session.add(datasource)
    db_session.flush()
    schema = CatalogSchema(
        project_id=project.id, datasource_id=datasource.id, schema_name="SRC",
    )
    db_session.add(schema)
    db_session.flush()
    catalog_table = CatalogTable(
        project_id=project.id, datasource_id=datasource.id, catalog_schema_id=schema.id,
        schema_name="SRC", table_name="ACCOUNT", table_comment="存款账户",
    )
    db_session.add(catalog_table)
    db_session.flush()
    db_session.add_all([
        CatalogColumn(
            project_id=project.id, datasource_id=datasource.id, catalog_table_id=catalog_table.id,
            schema_name="SRC", table_name="ACCOUNT", column_name="CUST_BAL",
            column_comment="客户存款余额", data_type="decimal(18,2)",
        ),
        CatalogColumn(
            project_id=project.id, datasource_id=datasource.id, catalog_table_id=catalog_table.id,
            schema_name="SRC", table_name="ACCOUNT", column_name="CUST_NO",
            column_comment="客户号", data_type="varchar(32)",
        ),
    ])
    db_session.commit()
    return {
        "db": db_session, "project": project, "user": user, "field": field,
        "principal": Principal(user.id, user.username, user.display_name),
    }


def _task(db, scope, *, scenario_key="regulatory_field_analysis", adaptive=False) -> AgentTask:
    task = AgentTask(
        institution_id=scope["project"].institution_id,
        project_id=scope["project"].id,
        objective="按监管口径分析目标字段来源",
        scenario_key=scenario_key,
        status=sm.TASK_CREATED,
        plan_version=1,
        created_by=scope["user"].id,
        adaptive=adaptive,
        result_summary_json={"subject": {"target_field_id": scope["field"].id}},
    )
    db.add(task)
    db.flush()
    return task


def _plan(db, task, steps) -> None:
    runtime.materialize_plan(db, task, planner.PlanDraft(
        objective=task.objective, scenario_key=task.scenario_key,
        subject={"target_field_id": task.result_summary_json["subject"]["target_field_id"]},
        steps=steps,
    ), planner_source="deterministic")
    db.commit()


def _run(db, scope, task) -> None:
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.expire_all()


def _step(db, task_id: int, key: str) -> AgentStep:
    step = (db.query(AgentStep).filter_by(task_id=task_id, step_key=key)
            .order_by(AgentStep.id.desc()).first())
    assert step is not None, f"step {key} 未落库"
    return step


# ---------------------------------------------------------------- 案例一：信息充分


def test_sufficient_information_runs_real_tools_and_stops_before_adoption(scope):
    """真实工具链执行完成，但没有任何已确认口径/映射被自动写入。"""
    from app.models import MartToYbtMapping, ScenarioBusinessMapping, SourceToMartMapping

    db = scope["db"]
    field_id = scope["field"].id
    task = _task(db, scope)
    _plan(db, task, [
        planner.PlannedStep(
            step_key="metadata", tool_key="search_metadata", reason="检索可用元数据",
            input={"query": "客户存款余额"},
        ),
        planner.PlannedStep(
            step_key="recall", tool_key="recall_field_candidates", reason="按口径召回候选字段",
            depends_on=["metadata"], input={"target_field_id": field_id},
        ),
        planner.PlannedStep(
            step_key="summary", tool_key="summarize_evidence", reason="汇总已收集证据",
            depends_on=["recall"], input={},
        ),
    ])
    _run(db, scope, task)

    assert db.get(AgentTask, task.id).status == sm.TASK_COMPLETED
    for key in ("metadata", "recall", "summary"):
        assert _step(db, task.id, key).status == sm.STEP_COMPLETED, key

    recall = _step(db, task.id, "recall")
    recall_summary = recall.output_summary_json or {}
    carry = recall_summary.get("carry") or {}
    candidates = carry.get("candidate_ids") or []
    assert candidates, "真实召回必须给出候选，而不是空结论"
    assert (carry.get("ranking_mode") or (recall_summary.get("summary") or {}).get("ranking_mode")) in {
        "deterministic_recall", "model_rerank",
    }

    # 人工采用边界：运行时不得自动写入确认状态或正式映射。
    assert db.query(ScenarioBusinessMapping).count() == 0
    assert db.query(SourceToMartMapping).count() == 0
    assert db.query(MartToYbtMapping).count() == 0
    artifacts = runtime.task_snapshot(db, db.get(AgentTask, task.id))["artifacts"]
    assert all(item.get("status") != "confirmed" for item in artifacts)


# ---------------------------------------------------------------- 案例二：缺少输入


def test_missing_generation_input_blocks_with_a_next_action(scope):
    """缺少需求生成输入时必须阻断并给出下一步，不能产出看似完成的空草稿。"""
    db = scope["db"]
    task = _task(db, scope)
    _plan(db, task, [
        planner.PlannedStep(
            step_key="candidate", tool_key="generate_requirement_candidate",
            reason="生成需求候选", input={"target_field_id": scope["field"].id},
        ),
    ])
    _run(db, scope, task)

    step = _step(db, task.id, "candidate")
    assert step.status == sm.STEP_BLOCKED, "缺少生成输入必须阻断，而不是降级成确定性草稿"
    step_summary = step.output_summary_json or {}
    gaps = step_summary.get("gaps") or []
    assert "requirement_input_missing" in {item.get("code") for item in gaps}
    next_action = (step_summary.get("carry") or {}).get("next_action") or {}
    assert next_action.get("code") == "create_requirement_input"
    assert str(next_action.get("follow_up_api", "")).endswith("generation-inputs")

    task_now = db.get(AgentTask, task.id)
    assert task_now.status == sm.TASK_BLOCKED
    assert not runtime.task_snapshot(db, task_now)["artifacts"], "阻断的步骤不得留下候选产物"


# ---------------------------------------------------------------- 案例三：Skill 未绑定


def test_unbound_rerank_skill_falls_back_explicitly_and_never_pins_a_version(scope):
    """没有固定采用的重排 Skill 时：标注回退 + 绑定待办，绝不静默绑定最新版本。"""
    db = scope["db"]
    bindings_before = db.query(AISkillScopeBinding).count()
    task = _task(db, scope)
    _plan(db, task, [
        planner.PlannedStep(
            step_key="rerank", tool_key="rerank_field_candidates", reason="重排候选",
            input={"target_field_id": scope["field"].id},
        ),
    ])
    _run(db, scope, task)

    step = _step(db, task.id, "rerank")
    assert step.status == sm.STEP_COMPLETED, "缺少绑定属于可解释的能力缺口，不应让整条链路失败"
    step_summary = step.output_summary_json or {}
    carry = step_summary.get("carry") or {}
    assert (carry.get("ranking_mode") or (step_summary.get("summary") or {}).get("ranking_mode")) == (
        "deterministic_recall"
    )
    assert (step_summary.get("model_metadata") or {}).get("degraded_reason") == "skill_binding_missing"
    binding_gap = (step_summary.get("summary") or {})
    assert "model_rerank" not in str(binding_gap), "回退路径不得被标记为模型重排"
    assert db.query(AISkillScopeBinding).count() == bindings_before, "系统不得自动创建绑定"


# ---------------------------------------------------------------- 案例四：需要人工确认


def _gated_tool(db, scope):
    """真实门控语义的最小工具：冲突 -> waiting_human；重复运行计数可观测。"""
    calls = {"n": 0}

    def handler(ctx) -> ToolResult:
        calls["n"] += 1
        return ToolResult(
            output={"round": calls["n"]},
            step_output={"round": calls["n"], "analysis": {"basis": "制度与实现对照"}},
            facts=[{
                "id": f"fact:{calls['n']}", "kind": "metric_fact", "value": {"round": calls["n"]},
                "source_type": "manual", "source_id": "p1a", "locator": "p1a",
            }],
            policy_comparisons=[{"status": "conflict", "fact_ids": [f"fact:{calls['n']}"],
                                 "policy_clause_ids": ["clause-1"]}],
        )

    key = _register("dec_gated", handler, requires_human_confirmation=True, risk_level="high")
    return key, calls


def test_human_confirmation_keeps_evidence_and_resumes_after_approval(scope):
    db = scope["db"]
    tool_key, calls = _gated_tool(db, scope)
    task = _task(db, scope)
    _plan(db, task, [
        planner.PlannedStep(step_key="compare", tool_key=tool_key, reason="制度与实现对照", input={}),
    ])
    _run(db, scope, task)

    step = _step(db, task.id, "compare")
    assert step.status == sm.STEP_WAITING_HUMAN
    assert db.get(AgentTask, task.id).status == sm.TASK_WAITING_HUMAN
    kept = (step.output_summary_json or {}).get("carry") or {}
    assert (kept.get("analysis") or {}).get("basis") == "制度与实现对照", "等待人工期间必须保留已完成分析证据"
    assert step.evidence_count >= 1, "等待人工期间证据引用不得丢失"

    runtime.decide(db, scope["principal"], db.get(AgentTask, task.id), step,
                   sm.DECISION_APPROVE, comment="证据可接受，同意继续")
    db.expire_all()
    runtime.resume_task(db, scope["principal"], db.get(AgentTask, task.id))
    db.expire_all()

    after = _step(db, task.id, "compare")
    assert after.status == sm.STEP_COMPLETED
    assert ((after.output_summary_json or {}).get("carry") or {}).get("analysis", {}).get("basis") == (
        "制度与实现对照"
    )
    assert db.get(AgentTask, task.id).status == sm.TASK_COMPLETED
    assert calls["n"] == 1, "人工通过后不应重复调用同一工具"


# ---------------------------------------------------------------- 案例五：人工否决


def test_human_rejection_cannot_be_retried_into_a_silent_re_adoption(scope):
    """被人工否决的步骤不能靠「重试」重跑同一结论，只能有界重规划。"""
    db = scope["db"]
    tool_key, calls = _gated_tool(db, scope)
    task = _task(db, scope)
    _plan(db, task, [
        planner.PlannedStep(step_key="compare", tool_key=tool_key, reason="制度与实现对照", input={}),
    ])
    _run(db, scope, task)

    step = _step(db, task.id, "compare")
    runtime.decide(db, scope["principal"], db.get(AgentTask, task.id), step,
                   sm.DECISION_REJECT, comment="结论不成立，否决")
    db.expire_all()
    rejected = _step(db, task.id, "compare")
    assert rejected.status == sm.STEP_BLOCKED
    assert rejected.error_code == "human_rejected"
    assert db.get(AgentTask, task.id).status == sm.TASK_BLOCKED
    assert calls["n"] == 1

    with pytest.raises(HTTPException) as failure:
        runtime.retry_task(db, scope["principal"], db.get(AgentTask, task.id))
    assert failure.value.status_code == 409
    assert failure.value.detail["error_code"] == "human_rejected_requires_replan"
    db.expire_all()
    assert _step(db, task.id, "compare").status == sm.STEP_BLOCKED, "重试不得重新跑被否决的步骤"
    assert calls["n"] == 1, "被否决的结论不得被静默重新生成"

    # 有边界的重规划是被允许的恢复路径：计划版本递增，被否决的步骤被标记跳过，
    # 由新计划重新收集证据（而不是把原结论悄悄放行）。
    rejected_step_id = rejected.id
    result = runtime.replan_task(db, scope["principal"], db.get(AgentTask, task.id))
    db.expire_all()
    assert result["plan_version"] == 2
    plan = (db.query(AgentPlan).filter_by(task_id=task.id)
            .order_by(AgentPlan.version_no.desc()).first())
    assert plan.version_no == 2
    original = db.get(AgentStep, rejected_step_id)
    assert original.status == sm.STEP_SKIPPED
    assert original.error_code == "replanned"
