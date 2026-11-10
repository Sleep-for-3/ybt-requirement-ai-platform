"""问答场景（knowledge_question）：只读、无人工网关、创建任务不被模型规划阻塞。

回归的是线上可复现的两个问题：

1. 问"某张表都有哪些字段"被当成字段口径分析，因为解析不出唯一分析对象而弹出
   ``subject_clarification`` 网关，用户看到的是"批准并继续"，但问答并不写任何东西。
2. 创建任务时同步跑模型规划，前端 60 秒超时放弃，任务其实已经在后台跑起来。
"""
from __future__ import annotations

import pytest

from app.models import (
    AgentArtifact,
    AgentStep,
    AgentTask,
    BackgroundJob,
    Institution,
    Project,
    ProjectMembership,
    User,
)
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.scenarios import SCENARIO_KNOWLEDGE_QUESTION, route_scenario
from app.services.agent.tools.registry import require_tool
from app.services.auth.dependencies import Principal
from app.services.rag import grounded_answer_service

QUESTION = "互联网贷款协议表都有哪些主要字段"


@pytest.fixture()
def scope(db_session):
    institution = Institution(
        institution_code="qa-bank", institution_name="问答银行", institution_type="bank", status="active",
    )
    user = User(username="qa_user", display_name="问答用户", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(
        name="问答项目", institution_id=institution.id, project_status="active",
        bank_name="问答银行", description="知识问答场景",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(
        project_id=project.id, user_id=user.id, project_role="project_manager", status="active",
    ))
    db_session.commit()
    return {
        "db": db_session, "project": project, "user": user,
        "principal": Principal(user.id, user.username, user.display_name),
    }


def test_objective_routes_to_question_scenario():
    routing = route_scenario(QUESTION)
    assert routing.scenario_key == SCENARIO_KNOWLEDGE_QUESTION
    assert routing.requires_clarification is False


def test_question_plan_uses_only_read_only_ungated_tools():
    draft = planner.deterministic_plan(QUESTION, scenario_key=SCENARIO_KNOWLEDGE_QUESTION, subject={})
    assert [step.tool_key for step in draft.steps] == ["search_metadata", "answer_knowledge_question"]
    for step in draft.steps:
        spec = require_tool(step.tool_key)
        assert spec.read_only is True, f"{step.tool_key} 必须只读"
        assert spec.requires_human_confirmation is False, f"{step.tool_key} 不得要求人工确认"


def test_read_only_comparison_tools_are_not_gated():
    """只读比对不是写操作，不能要求"批准并继续"。"""

    for tool_key in ("compare_policy_and_implementation", "compare_sql_versions"):
        spec = require_tool(tool_key)
        assert spec.read_only is True
        assert spec.requires_human_confirmation is False, f"{tool_key} 是只读工具，不应开人工网关"
        assert spec.risk_level in {"low", "medium"}


def test_create_task_defers_llm_planning_to_the_background_job(scope, monkeypatch):
    db = scope["db"]
    calls = {"n": 0}

    async def _must_not_run(*args, **kwargs):  # pragma: no cover - 被调用即失败
        calls["n"] += 1
        raise AssertionError("创建任务的请求内不允许执行模型规划")

    monkeypatch.setattr(planner, "plan_with_llm", _must_not_run)
    task = runtime.create_task(
        db, scope["principal"], scope["project"], QUESTION,
        use_llm_planner=True, defer_llm_plan=True,
    )
    assert calls["n"] == 0, "创建请求必须立即返回"
    assert task.result_summary_json.get("planner_pending") == "llm"
    assert task.adaptive is False, "问答没有可修订的计划，不应启用观察重规划"
    steps = db.query(AgentStep).filter_by(task_id=task.id).all()
    assert steps and {step.status for step in steps} == {sm.STEP_PENDING}


def test_question_task_completes_without_a_human_gate(scope, monkeypatch):
    db = scope["db"]

    async def _answer(database, project_id, query, **kwargs):
        assert kwargs.get("commit") is False, "工具运行在自己的事务里，不得中途提交"
        return {
            "answer": "互联网贷款协议表包含贷款余额、借款期限等主要字段。",
            "answer_status": "grounded",
            "citations": [{
                "knowledge_unit_id": 1, "label": "互联网贷款管理办法",
                "quoted_content": "互联网贷款应当报送贷款余额与借款期限。", "source_heading": "第三章",
            }],
        }

    monkeypatch.setattr(grounded_answer_service, "grounded_answer", _answer)
    task = runtime.create_task(db, scope["principal"], scope["project"], QUESTION, use_llm_planner=False)
    assert task.scenario_key == SCENARIO_KNOWLEDGE_QUESTION
    # 只建一行后台作业、直接调 handler：测试不依赖外部 celery/redis，也不换 session。
    job = BackgroundJob(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        idempotency_key=f"test-agent-qa-{task.id}", job_type=runtime.AGENT_JOB_TYPE, status="queued",
        payload_summary_json={"agent_task_id": task.id, "plan_version": task.plan_version},
        created_by=scope["user"].id,
    )
    db.add(job)
    db.flush()
    task.background_job_id = job.id
    db.commit()
    runtime.run_agent_task(db, job)
    db.expire_all()

    task = db.get(AgentTask, task.id)
    assert task.status == sm.TASK_COMPLETED
    steps = db.query(AgentStep).filter_by(task_id=task.id).all()
    assert not [step for step in steps if step.status == sm.STEP_WAITING_HUMAN], "问答不得停在人工网关"
    answer_step = next(step for step in steps if step.step_key == "answer_question")
    summary = (answer_step.output_summary_json or {}).get("summary") or {}
    assert "互联网贷款协议表包含" in str(summary.get("answer"))
    assert summary.get("citation_count") == 1
    artifacts = db.query(AgentArtifact).filter_by(task_id=task.id).all()
    assert [item.artifact_type for item in artifacts] == ["knowledge_answer"]
    assert artifacts[0].summary_json["answer"]


def test_create_endpoint_returns_a_pending_task_before_any_planning(scope, monkeypatch):
    """POST /projects/{id}/agent/tasks 必须秒回：返回时既没有规划、也没有执行任何步骤。"""

    db = scope["db"]
    from app.api.agent import create_agent_task
    from app.schemas.agent import AgentTaskCreate

    enqueued: list[BackgroundJob] = []

    class _RecordingQueue:
        def enqueue(self, database, **kwargs):
            job = BackgroundJob(
                institution_id=kwargs.get("institution_id"), project_id=kwargs.get("project_id"),
                idempotency_key=kwargs["idempotency_key"], job_type=kwargs["job_type"], status="queued",
                payload_summary_json=dict(kwargs.get("payload_summary") or {}),
                created_by=int(kwargs.get("created_by") or 0),
            )
            database.add(job)
            database.flush()
            enqueued.append(job)
            return job

    monkeypatch.setattr(runtime, "get_task_queue", lambda: _RecordingQueue())
    called = {"n": 0}

    async def _must_not_run(*args, **kwargs):  # pragma: no cover - 被调用即失败
        called["n"] += 1
        raise AssertionError("创建任务的响应里不允许已经跑过模型规划")

    monkeypatch.setattr(planner, "plan_with_llm", _must_not_run)
    body = create_agent_task(
        scope["project"].id, AgentTaskCreate(objective=QUESTION, auto_start=True),
        scope["principal"], db,
    )
    assert called["n"] == 0
    # 计划已落库（既有派生规则可能把"全 pending"显示为 running），但没有任何步骤执行或等待人工。
    assert body["task"]["status"] in {sm.TASK_CREATED, sm.TASK_RUNNING}
    assert body["task"]["scenario_key"] == SCENARIO_KNOWLEDGE_QUESTION
    assert body["task"]["result_summary"]["planner_pending"] == "llm"
    assert body["task"]["result_summary"]["adaptive"] is False
    assert [step["status"] for step in body["steps"]] == [sm.STEP_PENDING, sm.STEP_PENDING]
    assert len(enqueued) == 1, "任务必须已经进入后台队列，而不是停在请求里"

def test_question_falls_back_to_the_table_name_and_returns_its_fields(scope, monkeypatch):
    """「XX表都有哪些字段」的整句匹配不到表名，必须回退到核心词，并把字段一并带回。"""

    from app.models import BusinessSystem, SourceField, SourceTable

    db = scope["db"]
    system = BusinessSystem(project_id=scope["project"].id, system_code="LOAN", system_name="信贷系统")
    db.add(system)
    db.flush()
    table = SourceTable(
        project_id=scope["project"].id, business_system_id=system.id,
        table_code="T_LOAN_AGREEMENT", table_name="互联网贷款协议表",
    )
    db.add(table)
    db.flush()
    for code, name in (("F040001", "机构ID"), ("F040002", "协议ID")):
        db.add(SourceField(
            project_id=scope["project"].id, source_table_id=table.id,
            field_code=code, field_name=name, physical_column_name=code,
        ))
    db.commit()

    async def _no_documents(database, project_id, query, **kwargs):  # 知识库为空，只靠目录
        # 与线上一致：知识检索侧只给一句占位结论，不能拿它当最终回答。
        return {"answer": "现有知识库没有足够证据，结论待确认。",
                "answer_status": "needs_confirmation", "citations": []}

    monkeypatch.setattr(grounded_answer_service, "grounded_answer", _no_documents)
    task = runtime.create_task(db, scope["principal"], scope["project"], QUESTION, use_llm_planner=False)
    job = BackgroundJob(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        idempotency_key=f"test-agent-qa-fields-{task.id}", job_type=runtime.AGENT_JOB_TYPE, status="queued",
        payload_summary_json={"agent_task_id": task.id, "plan_version": task.plan_version},
        created_by=scope["user"].id,
    )
    db.add(job)
    db.flush()
    task.background_job_id = job.id
    db.commit()
    runtime.run_agent_task(db, job)
    db.expire_all()

    assert db.get(AgentTask, task.id).status == sm.TASK_COMPLETED
    steps = db.query(AgentStep).filter_by(task_id=task.id).all()
    assert not [step for step in steps if step.status == sm.STEP_WAITING_HUMAN]
    search_step = next(step for step in steps if step.step_key == "search_metadata")
    search_output = (search_step.output_summary_json or {}).get("summary") or {}
    assert "互联网贷款协议表" in search_output.get("search_terms", []), "必须用核心词再检索一次"
    assert search_output.get("registered_match_count", 0) >= 1

    answer_step = next(step for step in steps if step.step_key == "answer_question")
    summary = (answer_step.output_summary_json or {}).get("summary") or {}
    assert summary.get("answer_status") == "metadata_only", "知识库无文档时按目录作答，而不是空回答"
    assert "互联网贷款协议表" in str(summary.get("answer"))
    assert "F040001" in str(summary.get("answer")), "字段清单必须出现在回答里"
    assert summary.get("catalog_tables") == ["互联网贷款协议表"]
    assert len(summary.get("catalog_fields") or []) >= 2


def test_metadata_search_keeps_the_whole_question_first(scope):
    """原句能命中时不能被核心词改写行为（向后兼容）。"""

    from app.services.agent.tools.builtin import _question_core_terms

    assert _question_core_terms(QUESTION) == ["互联网贷款协议表"]
    assert _question_core_terms("F040001 是什么") == ["F040001"]
    assert _question_core_terms("互联网贷款协议表") == []

def test_physical_table_name_is_matched_exactly(scope, monkeypatch):
    """问物理表名时不能被相似度更高的别的表挤掉（hyf_ln_pa_online_info 案例）。"""

    from app.models import CatalogColumn, CatalogSchema, CatalogTable, DataSource

    db = scope["db"]
    datasource = DataSource(
        project_id=scope["project"].id, name="dm_bappdb_tcyl", db_type="postgresql",
        connection_params_json={}, readonly_flag=True, enabled=True, last_discovered_schemas_json=[],
    )
    db.add(datasource)
    db.flush()
    schema = CatalogSchema(project_id=scope["project"].id, datasource_id=datasource.id,
                           schema_name="dm_bappdb_tcyl", enabled=True)
    db.add(schema)
    db.flush()

    def add_table(name: str, comment: str, columns: list[str]) -> None:
        table = CatalogTable(
            project_id=scope["project"].id, datasource_id=datasource.id, catalog_schema_id=schema.id,
            schema_name=schema.schema_name, table_name=name, table_comment=comment, table_type="BASE TABLE",
            primary_key_columns_json=[], enabled=True,
        )
        db.add(table)
        db.flush()
        for position, column in enumerate(columns, start=1):
            db.add(CatalogColumn(
                project_id=scope["project"].id, datasource_id=datasource.id, catalog_table_id=table.id,
                schema_name=schema.schema_name, table_name=name, column_name=column, column_comment=column,
                nullable=True, ordinal_position=position, is_primary_key=False, enabled=True,
            ))

    add_table("hyf_ln_pa_online_info", "互联网贷款合作机构信息表", ["partner_no", "partner_nam", "partner_typ"])
    add_table("hyf_bk_inst_info", "机构信息表", ["financial_institution_typ"])
    db.commit()

    async def _no_documents(database, project_id, query, **kwargs):
        return {"answer": "现有知识库没有足够证据，结论待确认。",
                "answer_status": "needs_confirmation", "citations": []}

    monkeypatch.setattr(grounded_answer_service, "grounded_answer", _no_documents)
    task = runtime.create_task(
        db, scope["principal"], scope["project"], "hyf_ln_pa_online_info 表有哪些字段", use_llm_planner=False,
    )
    job = BackgroundJob(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        idempotency_key=f"test-agent-qa-exact-{task.id}", job_type=runtime.AGENT_JOB_TYPE, status="queued",
        payload_summary_json={"agent_task_id": task.id, "plan_version": task.plan_version},
        created_by=scope["user"].id,
    )
    db.add(job)
    db.flush()
    task.background_job_id = job.id
    db.commit()
    runtime.run_agent_task(db, job)
    db.expire_all()

    steps = db.query(AgentStep).filter_by(task_id=task.id).all()
    answer_step = next(step for step in steps if step.step_key == "answer_question")
    summary = (answer_step.output_summary_json or {}).get("summary") or {}
    assert summary.get("answer_status") == "metadata_only"
    assert summary.get("catalog_tables", [""])[0] == "hyf_ln_pa_online_info", "命中的必须是问句里的物理表"
    answer = str(summary.get("answer"))
    assert "hyf_ln_pa_online_info" in answer
    assert "partner_no" in answer
    assert "financial_institution_typ" not in answer

def test_answer_artifact_preserves_citation_version_and_locator(scope, monkeypatch):
    """「查看原文」需要的身份必须进产出物摘要：文档、版本、知识单元、Sheet/单元格。

    只保留 label/source_heading 时，前端只能打开当前版本、也无法定位；
    这条用例锁住摘要里的引用身份字段。
    """

    db = scope["db"]
    citation = {
        "citation_id": "knowledge-unit-77",
        "citation_type": "knowledge_document",
        "source_type": "regulatory_qa",
        "project_id": scope["project"].id,
        "document_id": 6,
        "document_version_id": 6,
        "knowledge_unit_id": 77,
        "label": "【知识库共享】一表通答疑汇总_[账号].xlsx",
        "source_file_name": "【知识库共享】一表通答疑汇总_[账号].xlsx",
        "source_sheet_name": "一表通制度问答",
        "source_cell_range": "A485:W485",
        "quoted_content": "问题：仅提供咨询服务的机构是否属于互联网贷款合作机构……",
        "locator": {"block_id": "knowledge-unit-77", "sheet_name": "一表通制度问答", "cell_range": "A485:W485",
                    "text_quote": "仅提供咨询服务的机构"},
        "href": "/knowledge/documents/6/preview?project_id=1&version_id=6",
        "effective_at": "2025-04-17",
        "authority_rank": 4,
    }

    async def _answer(database, project_id, query, **kwargs):
        return {"answer": "按答疑口径，仅提供咨询、数据类服务的机构不属于互联网贷款合作机构。",
                "answer_status": "grounded", "citations": [dict(citation)]}

    monkeypatch.setattr(grounded_answer_service, "grounded_answer", _answer)
    task = runtime.create_task(db, scope["principal"], scope["project"], QUESTION, use_llm_planner=False)
    job = BackgroundJob(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        idempotency_key=f"test-agent-qa-citation-{task.id}", job_type=runtime.AGENT_JOB_TYPE, status="queued",
        payload_summary_json={"agent_task_id": task.id, "plan_version": task.plan_version},
        created_by=scope["user"].id,
    )
    db.add(job)
    db.flush()
    task.background_job_id = job.id
    db.commit()
    runtime.run_agent_task(db, job)
    db.expire_all()

    artifact = db.query(AgentArtifact).filter_by(task_id=task.id).one()
    stored = artifact.summary_json["citations"][0]
    assert stored["document_id"] == 6
    assert stored["document_version_id"] == 6, "必须保留回答当时的版本，不能只留当前版本"
    assert stored["knowledge_unit_id"] == 77
    assert stored["source_sheet_name"] == "一表通制度问答"
    assert stored["source_cell_range"] == "A485:W485"
    assert stored["locator"]["cell_range"] == "A485:W485"
    assert stored["quoted_content"].startswith("问题：仅提供咨询服务")

def test_classification_items_are_only_listed_when_they_match_the_question_subject():
    """分类口径必须逐项对应问句对象；「合作方式」码值不能冒充「合作机构类型」。"""

    from app.services.agent.tools.builtin import _classification_result

    code_citation = {"quoted_content": (
        "反馈意见：同意浙江局意见。建议合作方式的码值修改为：。01 营销获客。02 联合贷款。"
        "03 支付结算。04 风险分担。05 担保增信。06 信息科技。07 逾期清收。08 客户筛选。"
        "09 部分风险评价。10 其他。00 无合作方。"
    )}
    listed = _classification_result("互联网贷款合作机构的合作方式有哪些码值？", [code_citation])
    assert listed and listed["status"] == "listed"
    assert [item["code"] for item in listed["items"]][:3] == ["01", "02", "03"]
    assert len(listed["items"]) == 11

    # 问的是「机构类型」，同一份原文讲的是「合作方式」，不能拿来充数。
    missing = _classification_result("互联网贷款合作机构类型有哪些？", [code_citation])
    assert missing and missing["status"] == "missing" and missing["items"] == []

    generic = {"quoted_content": (
        "问题类型：1.采集范围问题；表名（主）：互联网贷款合作协议；具体问题描述：仅提供咨询、"
        "数据类服务的机构是否属于互联网贷款合作机构；若需报送，合作方式、合作式类型应如何填报。"
    )}
    missing_generic = _classification_result("合作机构类型有哪些？", [generic])
    assert missing_generic and missing_generic["status"] == "missing"
    # 与分类无关的问题不注入分类段落。
    assert _classification_result("这张表有哪些字段？", [code_citation]) is None

def test_conflicts_detect_same_data_item_with_different_code_sets():
    """同一数据项的两份资料码值集合不同，才算冲突；同一口径的不同表述不算。"""

    from app.services.rag.grounded_answer_service import _evidence_conflicts

    def row(unit_id, content, rank=5):
        return {"knowledge_unit_id": unit_id, "authority_rank": rank, "content": content,
                "content_hash": f"hash-{unit_id}"}

    base = "表号（主）：6.25；数据项编码：F250007；数据项名称：合作方式；具体问题描述："
    old = row(1, base + "值域为（00,01,02,03,04,05,06,07,08）")
    new = row(2, base + "反馈意见：建议合作方式的码值修改为：01 营销获客。02 联合贷款。03 支付结算。"
                       "04 风险分担。05 担保增信。06 信息科技。07 逾期清收。08 客户筛选。09 部分风险评价。10 其他。00 无合作方。")
    conflicts = _evidence_conflicts([old, new])
    assert conflicts and conflicts[0]["topic"] == "F250007@6.25"
    assert set(conflicts[0]["citation_ids"]) == {"knowledge-unit-1", "knowledge-unit-2"}

    # 不同数据项不是同一口径冲突。
    other = row(3, "数据项编码：F090006；数据项名称：发卡合作机构代码；具体问题描述：字段限长。")
    assert _evidence_conflicts([old, other]) == []
    # 同一数据项但属于不同报表（适用范围不同），不互相判冲突。
    scoped = row(5, "表号（主）：6.9；数据项编码：F250007；数据项名称：合作方式；具体问题描述：值域（00,01）。")
    assert _evidence_conflicts([old, scoped]) == []
    # 同一码值集合、不同文字说明，不应报冲突。
    same = row(4, base + "值域为（00,01,02,03,04,05,06,07,08），多个用分号隔开。")
    assert _evidence_conflicts([old, same]) == []
    # 业务问答（权威等级 2）之间出现码值集合差异，同样必须提示待确认。
    low_old = row(6, base + "值域为（00,01,02）", rank=2)
    low_new = row(7, base + "建议码值：01 营销获客。02 联合贷款。03 支付结算。09 部分风险评价。", rank=2)
    low_conflicts = _evidence_conflicts([low_old, low_new])
    assert low_conflicts and low_conflicts[0]["topic"] == "F250007@6.25"
