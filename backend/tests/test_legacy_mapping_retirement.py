from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import target_fields
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    EvidenceReference,
    FieldAnalysisTask,
    FieldMappingDraft,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal, get_current_principal


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_authorized_route_is_retired_without_generation_or_mutation(monkeypatch) -> None:
    legacy_calls = 0

    async def forbidden_legacy_generator(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        raise AssertionError("retired route invoked the legacy generator")

    monkeypatch.setattr(
        target_fields,
        "generate_mapping_draft",
        forbidden_legacy_generator,
        raising=False,
    )

    with _client() as (client, sessions):
        fixture = _seed_field_and_draft(sessions)
        before = _legacy_state(sessions)
        response = client.post(
            f"/api/fields/{fixture['field_id']}/generate-mapping",
            json={
                "include_template": False,
                "include_documents": False,
                "include_sql_parse_results": False,
                "include_nl_task_results": False,
            },
        )
        after = _legacy_state(sessions)

    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "legacy-mapping-generator-retired",
        "message": "Legacy field mapping generation has been retired",
        "replacement_routes": [
            "/api/source-to-mart-mappings/{mapping_id}/generate-draft",
            "/api/mart-to-ybt-mappings/{mapping_id}/generate-draft",
        ],
    }
    assert legacy_calls == 0
    assert after == before


def test_missing_and_foreign_fields_do_not_disclose_retirement_detail() -> None:
    with _client() as (client, sessions):
        fixture = _seed_field_and_draft(sessions, suffix="SCOPE")

        missing = client.post(
            "/api/fields/999999/generate-mapping",
            json={},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Target field not found"

        viewer_id = _seed_viewer(sessions, fixture["project_id"])
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            viewer_id,
            "legacy-retirement-viewer",
            None,
        )
        forbidden = client.post(
            f"/api/fields/{fixture['field_id']}/generate-mapping",
            json={},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"] == "Missing project permission: technical.edit"
        assert "retired" not in forbidden.text.lower()

        app.dependency_overrides[get_current_principal] = lambda: Principal(
            999999,
            "foreign-user",
            None,
        )
        foreign = client.post(
            f"/api/fields/{fixture['field_id']}/generate-mapping",
            json={},
        )

    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "Project not found"
    assert "retired" not in foreign.text.lower()


def test_existing_draft_remains_readable_and_reviewable_after_retirement() -> None:
    with _client() as (client, sessions):
        fixture = _seed_field_and_draft(sessions, suffix="COMPAT")

        retired = client.post(
            f"/api/fields/{fixture['field_id']}/generate-mapping",
            json={},
        )
        assert retired.status_code == 410

        latest = client.get(f"/api/fields/{fixture['field_id']}/drafts/latest")
        assert latest.status_code == 200
        assert latest.json()["id"] == fixture["draft_id"]
        assert latest.json()["final_content"] == "历史人工草稿"

        reviewed = client.patch(
            f"/api/fields/drafts/{fixture['draft_id']}/review",
            json={"review_status": "approved", "final_content": "复核后的历史草稿"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["review_status"] == "approved"
        assert reviewed.json()["final_content"] == "复核后的历史草稿"


def test_obsolete_composite_constructor_has_no_production_module_or_reference() -> None:
    obsolete_module = REPO_ROOT / "app" / "services" / "mapping_generator.py"
    assert not obsolete_module.exists()

    forbidden = (
        "app.services.mapping_generator",
        "generate_mapping_draft",
        "legacy_field_mapping",
    )
    production_files = sorted((REPO_ROOT / "app").rglob("*.py"))
    offenders: list[str] = []
    for path in production_files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{token}")
    assert offenders == []


@contextmanager
def _client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        None,
        "legacy-system",
        "Legacy development mode",
        True,
    )
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_field_and_draft(sessions: sessionmaker, suffix: str = "BASE") -> dict[str, int]:
    with sessions() as db:
        project = Project(
            name=f"Legacy retirement {suffix}",
            bank_name="测试银行",
            description="保留历史草稿并退役竞争生成链",
        )
        db.add(project)
        db.flush()
        table = TargetTable(
            project_id=project.id,
            table_code=f"YBT_{suffix}",
            table_name="历史目标表",
        )
        db.add(table)
        db.flush()
        field = TargetField(
            project_id=project.id,
            target_table_id=table.id,
            field_code=f"FIELD_{suffix}",
            field_name="历史目标字段",
            field_type="varchar(64)",
            required_flag=True,
        )
        db.add(field)
        db.flush()
        task = FieldAnalysisTask(
            project_id=project.id,
            target_field_id=field.id,
            status="completed",
        )
        db.add(task)
        db.flush()
        draft = FieldMappingDraft(
            task_id=task.id,
            project_id=project.id,
            target_field_id=field.id,
            business_to_mart_rule="历史业务到集市规则",
            mart_to_ybt_rule="历史集市到一表通规则",
            confidence_level="medium",
            review_status="pending",
            final_content="历史人工草稿",
            evidence_completeness="medium",
        )
        db.add(draft)
        db.flush()
        db.add(
            EvidenceReference(
                draft_id=draft.id,
                evidence_type="document_chunk",
                source_id=1,
                source_name="历史制度",
                location_text="第一条",
                quoted_content="历史证据保持不变",
            )
        )
        db.commit()
        return {
            "project_id": int(project.id),
            "field_id": int(field.id),
            "draft_id": int(draft.id),
        }


def _legacy_state(sessions: sessionmaker) -> tuple[int, int, int, tuple[object, ...]]:
    with sessions() as db:
        counts = (
            int(db.scalar(select(func.count(FieldAnalysisTask.id))) or 0),
            int(db.scalar(select(func.count(FieldMappingDraft.id))) or 0),
            int(db.scalar(select(func.count(EvidenceReference.id))) or 0),
        )
        draft = db.scalar(select(FieldMappingDraft).order_by(FieldMappingDraft.id.desc()))
        assert draft is not None
        return counts + (
            (
                draft.id,
                draft.task_id,
                draft.project_id,
                draft.target_field_id,
                draft.business_to_mart_rule,
                draft.mart_to_ybt_rule,
                draft.review_status,
                draft.final_content,
                draft.updated_at,
            ),
        )


def _seed_viewer(sessions: sessionmaker, project_id: int) -> int:
    with sessions() as db:
        user = User(
            username="legacy-retirement-viewer",
            display_name="Legacy retirement viewer",
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(
            ProjectMembership(
                project_id=project_id,
                user_id=user.id,
                project_role="viewer",
                status="active",
                created_by=user.id,
            )
        )
        db.commit()
        return int(user.id)
