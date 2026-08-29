from pathlib import Path

from fastapi import Response

from app.api.jobs import project_jobs_summary
from app.api.requirement_workspace import requirement_workspace, requirement_workspace_field
from app.core.settings import Settings
from app.models import BackgroundJob, ProductScenario, Project, TargetField, TargetTable
from app.services.auth.dependencies import Principal


ROOT = Path(__file__).resolve().parents[2]


def test_production_rejects_inline_queue_and_sqlite() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        auth_mode="required",
        app_secret_key="production-app-secret",
        jwt_secret_key="production-jwt-secret-with-more-than-32-characters",
        cors_origins="https://product.example.com",
        database_url="sqlite:///./production.db",
        task_queue_provider="inline",
    )

    codes = {item["code"] for item in settings.validate_configuration() if item["severity"] == "error"}

    assert "production_database_not_postgresql" in codes
    assert "production_task_queue_not_celery" in codes


def test_production_docker_contract_uses_next_start_celery_and_postgresql() -> None:
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    development_dockerfile = (ROOT / "frontend" / "Dockerfile.dev").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    development_compose = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")

    assert dockerfile.count("FROM node:20-alpine") >= 2
    assert 'CMD ["npm", "run", "start"' in dockerfile
    assert "npm run dev" not in dockerfile
    assert "NODE_ENV=production" in dockerfile
    assert 'CMD ["npm", "run", "dev"' in development_dockerfile
    assert "TASK_QUEUE_PROVIDER: celery" in compose
    assert "ENVIRONMENT: production" in compose
    assert "postgresql+psycopg://" in compose
    assert "TASK_QUEUE_PROVIDER: inline" in development_compose
    assert "sqlite:" in development_compose


def test_project_job_summary_returns_only_active_counts(db_session) -> None:
    project = Project(name="任务汇总项目")
    db_session.add(project)
    db_session.flush()
    for index, status in enumerate(("queued", "running", "running", "completed", "failed"), start=1):
        db_session.add(BackgroundJob(
            project_id=project.id,
            idempotency_key=f"summary-{index}",
            job_type="batch_ai_generation_business",
            status=status,
            created_by=1,
        ))
    db_session.commit()
    response = Response()

    result = project_jobs_summary(
        project.id,
        Principal(None, "legacy-system", "Legacy development mode", True),
        response,
        db_session,
    )

    assert result == {"queued_count": 1, "running_count": 2, "active_count": 3}
    assert response.headers["Server-Timing"].startswith("jobs_summary;dur=")
    assert int(response.headers["X-Response-Payload-Bytes"]) > 0


def test_windows_launcher_uses_a_production_build_and_next_start() -> None:
    launcher = (ROOT / "scripts" / "项目启停.ps1").read_text(encoding="utf-8")

    assert '@("run", "build")' in launcher
    assert '@("run", "start", "--", "-H", "127.0.0.1"' in launcher
    assert '$env:NEXT_DIST_DIR = if ($Mode -eq "production") { ".next" } else { ".next-dev" }' in launcher


def test_workspace_endpoints_report_timing_payload_and_query_count(db_session) -> None:
    project = Project(name="性能观测项目")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="OBS", table_name="观测表")
    scenario = ProductScenario(project_id=project.id, scenario_code="BASE", scenario_name="基础", enabled=True)
    db_session.add_all([table, scenario])
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id, field_code="F1", field_name="字段")
    db_session.add(field)
    db_session.commit()
    principal = Principal(None, "legacy-system", "Legacy development mode", True)

    projection_response = Response()
    requirement_workspace(project.id, principal, projection_response, table.id, scenario.id, db_session)
    detail_response = Response()
    requirement_workspace_field(project.id, field.id, principal, detail_response, scenario.id, db_session)

    assert "workspace_projection;dur=" in projection_response.headers["Server-Timing"]
    assert int(projection_response.headers["X-Response-Payload-Bytes"]) > 0
    assert int(projection_response.headers["X-DB-Query-Count"]) <= 16
    assert "workspace_field_detail;dur=" in detail_response.headers["Server-Timing"]
    assert int(detail_response.headers["X-Response-Payload-Bytes"]) > 0
