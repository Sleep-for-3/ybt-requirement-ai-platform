"""Loopback-only real HTTP fixture; no production DB or real provider access."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(DATABASE_URL="sqlite:///:memory:", CORS_ORIGINS="*", AUTH_MODE="required",
                  LLM_PROVIDER="mock", EMBEDDING_PROVIDER="mock", VECTOR_STORE_PROVIDER="mock", TASK_QUEUE_PROVIDER="inline")

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.core.database import Base, get_db
from app.main import app
from app.models import AISkillDefinition, Institution, InstitutionMembership, ModelProfile, Project, ProjectMembership, User
from app.services.auth.dependencies import Principal, get_current_principal
from test_lineage_graph_contract import _seed_chain
from test_ai_skill_runtime import envelope

temporary = tempfile.TemporaryDirectory(prefix="ai-skill-browser-")
engine = create_engine(f"sqlite:///{(Path(temporary.name) / 'fixture.sqlite3').as_posix()}", connect_args={"check_same_thread": False})
@event.listens_for(engine, "connect")
def foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
Base.metadata.create_all(engine)
factory = sessionmaker(engine, expire_on_commit=False)
with factory() as db:
    seeded = _seed_chain(db, code="SKILL_BROWSER")
    project = db.get(Project, seeded["project_id"])
    project.name = "AI Skill 浏览器隔离项目"
    manager = db.scalar(select(User).where(User.username == "graph-user-SKILL_BROWSER"))
    approver = User(username="skill-browser-approver", display_name="独立审批人", status="active")
    db.add(approver)
    db.flush()
    db.add_all([ProjectMembership(project_id=project.id, user_id=manager.id, project_role="project_manager", status="active"),
                InstitutionMembership(institution_id=project.institution_id, user_id=approver.id, role="institution_admin", status="active"),
                ModelProfile(profile_name="隔离 Mock", provider_type="mock", model_name="mock-skill", enabled=True, local_only=True, max_context_tokens=64000),
                AISkillDefinition(skill_key="lineage_edge_explanation", task_key="lineage_edge_explanation", display_name="血缘关系解释", created_by=manager.id)])
    db.commit()
    principals = {"skill-manager": Principal(manager.id, manager.username, manager.display_name),
                  "skill-approver": Principal(approver.id, approver.username, approver.display_name)}
    operator = Institution(institution_code="skill-browser-platform", institution_name="隔离平台", institution_type="platform_operator")
    administrator = User(username="skill-browser-platform", display_name="隔离平台管理员", status="active")
    db.add_all([operator, administrator]); db.flush()
    db.add(InstitutionMembership(institution_id=operator.id, user_id=administrator.id, role="institution_admin", status="active"))
    db.commit()
    principals["skill-platform"] = Principal(administrator.id, administrator.username, administrator.display_name)
    scope = {"scope_type": "project", "institution_id": project.institution_id, "project_id": project.id}
    fixture = {**seeded, "scope": scope, "test_case": {"name": "隔离血缘基础契约", "input": envelope(scope).model_dump(mode="json")}}
    if os.environ.get("SKILL_ACCEPTANCE_B2") == "1":
        from test_requirement_draft_snapshots import fixture as requirement_fixture
        from test_ai_skill_requirement import sample
        req_project, field, requirement, _ = requirement_fixture(db)
        db.add_all([
            ProjectMembership(project_id=req_project.id, user_id=manager.id, project_role="project_manager", status="active"),
            InstitutionMembership(institution_id=req_project.institution_id, user_id=approver.id, role="institution_admin", status="active"),
            AISkillDefinition(skill_key="requirement_candidate_generation", task_key="requirement_candidate_generation", display_name="需求候选", created_by=manager.id),
        ])
        db.commit()
        req_scope = {"scope_type": "project", "institution_id": req_project.institution_id, "project_id": req_project.id}
        fixture["requirement"] = {"scope": req_scope, "id": requirement.id, "field_id": field.id,
            "table_id": requirement.scope_json["target_table_id"], "scenario_id": requirement.scope_json["scenario_id"],
            "model_profile_id": db.scalar(select(ModelProfile.id)),
            "test_case": {"name": "隔离需求基础契约", "input": sample(req_scope).model_dump(mode="json")}}
        from test_ai_skill_mapping import sample as mapping_sample
        fixture["requirement"]["mapping_test_cases"] = {}
        for key in ("scenario_business_mapping", "scenario_technical_lineage"):
            db.add(AISkillDefinition(skill_key=key, task_key=key, display_name=key, created_by=manager.id))
            fixture["requirement"]["mapping_test_cases"][key] = {
                "name": "隔离场景映射契约", "input": mapping_sample(key, req_scope).model_dump(mode="json")}
        db.commit()

if os.environ.get("SKILL_ACCEPTANCE_B3") == "1":
    from app.models import CatalogColumn, CatalogSchema, CatalogTable, DataSource
    with factory() as db:
        req_info = fixture["requirement"]
        project_id = req_info["scope"]["project_id"]
        source = DataSource(project_id=project_id, name="候选隔离目录", db_type="postgresql",
                            host="NEVER_CONNECT", encrypted_password="NEVER_EXPOSE", database_name="fixture_bank", enabled=True)
        db.add(source); db.flush()
        if os.environ.get("SKILL_ACCEPTANCE_PREPARE") == "1":
            import sqlite3
            membership = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == principals["skill-manager"].user_id))
            membership.project_role = "technical_analyst"
            source_path = Path(temporary.name) / "synthetic-source.sqlite3"
            with sqlite3.connect(source_path) as connection:
                connection.execute("create table fixture_account (balance numeric, account_id integer)")
                connection.executemany("insert into fixture_account values (?, ?)", [(100, 1), (200, 2), (None, 3)])
            source.db_type = "sqlite"
            source.database_name = str(source_path)
            source.readonly_flag = True
            source.host = None
            source.encrypted_password = None
        schema = CatalogSchema(project_id=project_id, datasource_id=source.id, schema_name="public", enabled=True)
        db.add(schema); db.flush()
        table = CatalogTable(project_id=project_id, datasource_id=source.id, catalog_schema_id=schema.id,
                             schema_name="public", table_name="fixture_account", enabled=True)
        db.add(table); db.flush()
        for name, enabled in (("balance", True), ("account_id", True), ("disabled_secret", False)):
            db.add(CatalogColumn(project_id=project_id, datasource_id=source.id, catalog_table_id=table.id,
                                 schema_name="public", table_name=table.table_name, column_name=name,
                                 column_comment="合成账户字段", data_type="numeric", nullable=False, enabled=enabled))
        db.commit()
        if os.environ.get("SKILL_ACCEPTANCE_PREPARE") == "1":
            schema.schema_name = "main"
            table.schema_name = "main"
            for column in db.scalars(select(CatalogColumn).where(CatalogColumn.catalog_table_id == table.id)):
                column.schema_name = "main"
            db.commit()
        req_info["catalog_datasource_id"] = source.id

def isolated_db():
    with factory() as db:
        yield db

def fixture_principal(request: Request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    if token not in principals:
        raise HTTPException(401, "Fixture identity required")
    return principals[token]

app.dependency_overrides[get_db] = isolated_db
app.dependency_overrides[get_current_principal] = fixture_principal

if os.environ.get("SKILL_ACCEPTANCE_POLICY") == "1":
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.requirements import router as requirement_router
    from app.models import Requirement, TargetField
    from test_requirement_policy_comparison import setup_comparison
    from app.services.ai_skills import runtime
    from app.services.llm.mock import MockLLMService
    with factory() as db:
        req_info = fixture["requirement"]
        req = db.get(Requirement, req_info["id"])
        req_project = db.get(Project, req.project_id)
        field = db.get(TargetField, req_info["field_id"])
        membership = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == req.project_id, ProjectMembership.user_id == principals["skill-manager"].user_id))
        setup_app = FastAPI()
        setup_app.include_router(requirement_router)
        setup_app.dependency_overrides[get_db] = lambda: db
        setup_app.dependency_overrides[get_current_principal] = lambda: principals["skill-manager"]
        with TestClient(setup_app) as client:
            _, unit, _, view, _ = setup_comparison((client, db, req_project, field, req, membership))
        req_info["policy"] = {"unit_id": unit.id, "view": view, "content_version": 2}
        db.commit()
        from app.services.ai_skills.document_context import build_document_envelope
        _, document_envelope = build_document_envelope(db, principals["skill-manager"], req.project_id, req.id, 2)
        req_info["document_test_case"] = {"name": "固定文档合成用例", "input": document_envelope.model_dump(mode="json")}
    class PolicyFixtureModel(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            result = await super().chat_json(system_prompt, user_prompt)
            if system_prompt.startswith("[AI_SKILL_DOCUMENT_V1]"):
                import re
                match = re.search(r'"id": "(revision:\d+:requirement)"', user_prompt)
                if match:
                    result["candidate"]["background"] = [{"text": "合成背景整理，须人工核验。", "fact_ids": [match.group(1)]}]
            rule_id = req_info["policy"]["view"]["rules"][0]["rule_id"]
            if system_prompt.startswith("[AI_SKILL_REQUIREMENT_V1]") and rule_id in user_prompt:
                result["candidate"].update(script_rule_ids=[rule_id], policy_comparisons=[{
                    "unit_id": req_info["policy"]["unit_id"], "rule_ids": [rule_id], "status": "matched",
                    "explanation": "合成模型匹配建议，用于验证不覆盖人工冲突。", "difference": ""}])
            return result
    runtime.get_runtime_llm_service = lambda *args, **kwargs: PolicyFixtureModel()

if os.environ.get("SKILL_ACCEPTANCE_CROSS_LAYER") == "1":
    from test_double_layer_mapping import _seed_source_mapping, _seed_mart_to_ybt_mapping
    from test_ai_skill_mapping import sample as mapping_sample
    fixture["cross_layer"] = []
    with factory() as db:
        for kind in ("source_to_mart", "mart_to_ybt"):
            seed = _seed_source_mapping(db, "browser-" + kind)
            project = seed["project"]
            project.institution_id = scope["institution_id"]
            row = seed["mapping"] if kind == "source_to_mart" else _seed_mart_to_ybt_mapping(db, seed, "browser-" + kind)
            key = kind + "_mapping"
            db.add(ProjectMembership(project_id=project.id, user_id=principals["skill-manager"].user_id,
                project_role="project_manager", status="active"))
            db.add(AISkillDefinition(skill_key=key, task_key=key, display_name=key, created_by=principals["skill-manager"].user_id))
            db.commit()
            item_scope = {"scope_type": "project", "project_id": project.id, "institution_id": project.institution_id}
            fixture["cross_layer"].append({"kind": kind, "id": row.id, "scope": item_scope,
                "model_profile_id": db.scalar(select(ModelProfile.id)),
                "test_case": {"name": "跨层映射隔离用例", "input": mapping_sample(key, item_scope).model_dump(mode="json")}})

if os.environ.get("SKILL_ACCEPTANCE_PLANNED") == "1":
    from test_planned_search import seed_document
    with factory() as db:
        req_info = fixture["requirement"]
        req_info["planned_unit_ids"] = [seed_document(db, req_info["scope"]["project_id"], content)
            for content in ("余额 balance 合成资料", "利率 interest_rate 合成资料")]
        seed_document(db, req_info["scope"]["project_id"], "余额 利率 已失效资料", expired=True)
        db.commit()

if os.environ.get("SKILL_ACCEPTANCE_RECHECK") == "1":
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.requirements import router as requirement_router
    from app.models import Requirement, TargetField, ScriptFile
    from test_requirement_uat import confirmed_sample
    with factory() as db:
        req_info = fixture["requirement"]
        req = db.get(Requirement, req_info["id"])
        req_project = db.get(Project, req.project_id)
        field = db.get(TargetField, req_info["field_id"])
        membership = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == req.project_id,
            ProjectMembership.user_id == principals["skill-manager"].user_id))
        setup_app = FastAPI()
        setup_app.include_router(requirement_router)
        setup_app.dependency_overrides[get_db] = lambda: db
        setup_app.dependency_overrides[get_current_principal] = lambda: principals["skill-manager"]
        with TestClient(setup_app) as client:
            confirmed_sample((client, db, req_project, field, req, membership))
        script = db.scalar(select(ScriptFile).where(ScriptFile.project_id == req.project_id))
        script.current_version_no += 1
        db.commit()
        req_info["recheck_content_version"] = 4
if os.environ.get("SKILL_ACCEPTANCE_FIELD_RERANK") == "1":
    from test_ai_skill_field_rerank import envelope_for
    with factory() as db:
        req_info = fixture["requirement"]
        item_scope = req_info["scope"]
        definition = AISkillDefinition(skill_key="field_semantic_matching", task_key="field_semantic_matching",
                                       display_name="字段候选重排", created_by=principals["skill-manager"].user_id)
        db.add(definition)
        db.commit()
        fixture["field_rerank"] = {"scope": item_scope, "project_id": item_scope["project_id"],
                                  "field_id": req_info["field_id"], "datasource_id": req_info["catalog_datasource_id"],
                                  "model_profile_id": db.scalar(select(ModelProfile.id)),
                                  "test_case": {"name": "隔离字段重排契约",
                                                "input": envelope_for(item_scope).model_dump(mode="json")}}
@app.get("/__fixture")
def fixture_details():
    return fixture

if __name__ == "__main__":
    import uvicorn
    try:
        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), lifespan="off", access_log=False)
    finally:
        engine.dispose()
        temporary.cleanup()
