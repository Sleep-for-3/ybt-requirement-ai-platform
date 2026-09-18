"""Disposable loopback fixture for browser acceptance; no environment files or real accounts."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import settings as settings_module

workspace = TemporaryDirectory(prefix="reverse-browser-")
sample_directory = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
settings = settings_module.Settings(_env_file=None, database_url="sqlite://", environment="test",
    auth_mode="required", llm_provider="mock", embedding_provider="mock", vector_store_provider="mock",
    task_queue_provider="inline", storage_provider="local", storage_dir=workspace.name, cors_origins="*",
    app_secret_key="isolated-browser-synthetic", jwt_secret_key="isolated-browser-synthetic")
settings_module.get_settings = lambda: settings
settings_module.Settings.model_config["env_file"] = None

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database import Base, get_db
from app.models import (Institution, InstitutionMembership, Project, ProjectMembership,
    User, TargetTable, TargetField, ProductScenario, Requirement, BusinessSystem)
from app.api.requirements import router
from app.services.auth.dependencies import Principal, get_current_principal
from test_requirement_paths import setup_path
from app.services.storage import get_storage_service

# Browser requests span worker threads; use a disposable file with a real pool.
engine = create_engine("sqlite:///" + (Path(workspace.name) / "acceptance.sqlite").as_posix(),
    connect_args={"check_same_thread": False, "timeout": 30})
Base.metadata.create_all(engine)
with Session(engine) as db:
    user = User(username="isolated-reverse-browser", display_name="隔离需求验收", status="active")
    db.add(user); db.flush()
    principal = Principal(user.id, user.username, user.display_name)
    reviewers = {}
    for role in ("business_reviewer", "technical_reviewer", "final_reviewer"):
        reviewer = User(username=f"isolated-browser-{role}", display_name=f"隔离验收 {role}", status="active")
        db.add(reviewer); db.flush()
        reviewers[role] = Principal(reviewer.id, reviewer.username, reviewer.display_name)
    seed_app = FastAPI()
    seed_app.include_router(router)
    seed_app.dependency_overrides[get_db] = lambda: db
    seed_app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(seed_app) as client:
        for index, multilayer in enumerate((False, True), 1):
            bank = Institution(institution_code=f"reverse-browser-{index}", institution_name=f"隔离银行{index}")
            db.add(bank); db.flush()
            project = Project(name="隔离多层数仓项目" if multilayer else "隔离直达报送项目", institution_id=bank.id)
            db.add(project); db.flush()
            db.add(BusinessSystem(project_id=project.id,system_code="CORE",system_name=f"隔离银行{index}核心系统"))
            membership = ProjectMembership(project_id=project.id, user_id=user.id, project_role="project_manager", status="active")
            db.add(membership)
            for role, reviewer in reviewers.items():
                db.add(ProjectMembership(project_id=project.id, user_id=reviewer.user_id, project_role=role, status="active"))
            db.add(InstitutionMembership(institution_id=bank.id, user_id=user.id, role="institution_admin", status="active"))
            table = TargetTable(project_id=project.id, table_code="REPORT", table_name="隔离余额监管表")
            scenario = ProductScenario(project_id=project.id, scenario_code="PERIOD_END", scenario_name="期末余额")
            db.add_all([table, scenario]); db.flush()
            field = TargetField(project_id=project.id, target_table_id=table.id, field_code="amount", field_name="期末金额")
            db.add(field); db.flush()
            requirement = Requirement(project_id=project.id, name=f"{project.name}需求", version=1,
                scope_json={"target_table_id": table.id, "scenario_id": scenario.id, "field_ids": [field.id],
                    "document_ids": [], "source_table_ids": [], "mart_table_ids": [], "background": "隔离合成浏览器样本",
                    "objective": "核验完整依赖", "inclusion": "期末账户", "exclusion": "", "effective_date": None})
            db.add(requirement); db.flush()
            base, unit, basis_payload = setup_path((client, db, project, field, requirement, membership), multilayer,
                missing="--exception-cases" in sys.argv and index==2,storage=get_storage_service())
            if "--exception-cases" in sys.argv and index==1:
                unit.content = "期末余额必须按金额乘二报送，不能直接取原值。"
                db.flush()
                preview = client.post(f"/projects/{project.id}/requirements/script-preview",
                    json={"script_version_ids":basis_payload["script_version_ids"]}).json()
                basis_payload.update(expected_content_version=2,preview_hash=preview["preview_hash"])
                confirmed = client.post(base+"/script-basis",json=basis_payload)
                assert confirmed.status_code==201,confirmed.text
            if "--exception-cases" in sys.argv and index==2:
                from app.models import KnowledgeDocumentVersion
                db.get(KnowledgeDocumentVersion,unit.document_version_id).lifecycle_status="expired"
                db.flush()
            if sample_directory:
                from sqlalchemy import select
                from app.models import TemplateVersion
                extra = TargetTable(project_id=project.id,table_code="REPORT_EXTRA",table_name="隔离补充监管表")
                db.add(extra);db.flush()
                db.add(TargetField(project_id=project.id,target_table_id=extra.id,field_code="amount",field_name="补充金额"))
                template = db.scalar(select(TemplateVersion).where(TemplateVersion.project_id==project.id))
                template.parsed_snapshot_json = [*template.parsed_snapshot_json,{"table_code":"REPORT_EXTRA"}]
        db.commit()

if sample_directory:
    from zipfile import ZipFile
    from test_resource_batch_import import dictionary
    samples = Path(sample_directory); samples.mkdir(parents=True,exist_ok=True)
    (samples / "dictionary.xlsx").write_bytes(dictionary())
    (samples / "structures.ddl").write_text("CREATE TABLE bank.reg.report (amount DECIMAL);\nCREATE TABLE bank.reg.report_extra (amount DECIMAL);",encoding="utf-8")
    (samples / "conflict.ddl").write_text("CREATE TABLE bank.ods.accounts (amount VARCHAR(30), extra_flag INT);",encoding="utf-8")
    (samples / "invalid.ddl").write_text("not valid ddl",encoding="utf-8")
    (samples / "import-direct.sql").write_text("INSERT INTO bank.reg.report (amount) SELECT amount FROM bank.ods.accounts;",encoding="utf-8")
    (samples / "import-extra.sql").write_text("INSERT INTO bank.reg.report_extra (amount) SELECT amount FROM bank.ods.accounts;",encoding="utf-8")
    with ZipFile(samples / "scripts.zip","w") as archive:
        archive.writestr("nested/check.sql","SELECT amount FROM bank.ods.accounts;")
    multi = samples / "multilayer"; multi.mkdir(exist_ok=True)
    for name in ("dictionary.xlsx","conflict.ddl","invalid.ddl","scripts.zip"):
        (multi / name).write_bytes((samples / name).read_bytes())
    (multi / "structures.ddl").write_text("\n".join(
        f"CREATE TABLE bank.{name} (amount DECIMAL);" for name in
        ("dwd.accounts","dws.accounts","reg.report","reg.report_extra")),encoding="utf-8")
    for name,source,target in (("import-source.sql","ods.accounts","dwd.accounts"),
        ("import-mid.sql","dwd.accounts","dws.accounts"),("import-direct.sql","dws.accounts","reg.report"),
        ("import-extra.sql","dws.accounts","reg.report_extra")):
        (multi / name).write_text(f"INSERT INTO bank.{target} (amount) SELECT amount FROM bank.{source};",encoding="utf-8")

from app.main import app

def isolated_db():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_db] = isolated_db

def isolated_principal(request: Request):
    # Fixture-only actors for UI role switching; production app never installs this override.
    return reviewers.get(request.headers.get("x-isolated-review-role"), principal)

app.dependency_overrides[get_current_principal] = isolated_principal

if "--generation-failure-once" in sys.argv:
    from app.services import requirement_generation_worker as generation_worker
    original_generate = generation_worker.generate_candidate
    failure_pending = True

    def isolated_generation(db, row, item, project):
        global failure_pending
        if failure_pending:
            failure_pending = False
            raise RuntimeError("isolated synthetic provider unavailable once")
        return original_generate(db,row,item,project)

    generation_worker.generate_candidate = isolated_generation

if __name__ == "__main__":
    import uvicorn
    try:
        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), lifespan="off", access_log=False)
    finally:
        engine.dispose()
        workspace.cleanup()
