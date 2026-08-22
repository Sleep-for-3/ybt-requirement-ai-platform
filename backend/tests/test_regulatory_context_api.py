from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import regulatory_context as regulatory_context_api
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    Institution,
    Project,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    TargetField,
    TargetTable,
)
from app.schemas.regulatory_context import RegulatoryContext
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.permission_service import PermissionService
from app.services.semantic.context_builder import RegulatoryContextBuilder


AS_OF = date(2026, 6, 30)


def test_endpoint_uses_locked_authorization_and_builder_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permission_calls: list[tuple[int, str]] = []
    build_calls: list[tuple[object, int]] = []
    real_permission_service = PermissionService
    real_builder = RegulatoryContextBuilder

    class RecordingPermissionService:
        def __init__(self, db: Session, principal: Principal) -> None:
            self._delegate = real_permission_service(db, principal)

        def require_project_permission(self, project_id: int, permission: str) -> Project:
            permission_calls.append((project_id, permission))
            return self._delegate.require_project_permission(project_id, permission)

    class RecordingBuilder:
        def __init__(self, db: Session) -> None:
            self._delegate = real_builder(db)

        def build(self, request: object, *, authorized_project: Project) -> RegulatoryContext:
            build_calls.append((request, authorized_project.id))
            return self._delegate.build(request, authorized_project=authorized_project)

    monkeypatch.setattr(regulatory_context_api, "PermissionService", RecordingPermissionService)
    monkeypatch.setattr(regulatory_context_api, "RegulatoryContextBuilder", RecordingBuilder)

    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        response = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context",
            params={
                "target_table_id": fixture["target_table_id"],
                "target_field_id": fixture["target_field_id"],
                "semantic_concept_id": fixture["semantic_concept_id"],
                "as_of": AS_OF.isoformat(),
                "reporting_period": " 2026   H1 ",
                "mode": "trusted",
            },
        )

    assert response.status_code == 200, response.text
    assert permission_calls == [(fixture["project_id"], "project.view")]
    assert len(build_calls) == 1
    request, authorized_project_id = build_calls[0]
    assert request.project_id == fixture["project_id"]
    assert request.target_table_id == fixture["target_table_id"]
    assert request.target_field_id == fixture["target_field_id"]
    assert request.semantic_concept_id == fixture["semantic_concept_id"]
    assert request.as_of == AS_OF
    assert request.reporting_period == "2026 H1"
    assert authorized_project_id == fixture["project_id"]

    context = RegulatoryContext.model_validate(response.json())
    assert context.scope.project_id == fixture["project_id"]
    assert context.scope.as_of == AS_OF
    assert context.semantic[0].value.semantic_concept_version_id == fixture["semantic_version_id"]
    assert set(response.json()) == {
        "context_schema_version",
        "scope",
        "target",
        "scenario",
        "semantic",
        "regulatory",
        "metadata",
        "candidates",
        "mappings",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
        "conflicts",
        "open_questions",
        "build_metadata",
    }
    assert not _contains_planning_requirement_ids(response.json())


def test_unauthorized_request_never_invokes_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_called = False

    class ForbiddenBuilder:
        def __init__(self, db: Session) -> None:
            nonlocal build_called
            build_called = True

        def build(self, *args: object, **kwargs: object) -> RegulatoryContext:
            raise AssertionError("builder must not run before project authorization")

    monkeypatch.setattr(regulatory_context_api, "RegulatoryContextBuilder", ForbiddenBuilder)

    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            987654,
            "outsider",
            None,
        )
        response = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context",
            params={"as_of": AS_OF.isoformat()},
        )

    assert response.status_code == 404
    assert build_called is False
    assert "regulatory" not in response.text.lower()


def test_cross_project_target_is_a_stable_scoped_error() -> None:
    with _regulatory_client() as (client, sessions):
        first = _seed_acceptance_target(sessions, suffix="A")
        second = _seed_acceptance_target(sessions, suffix="B")
        response = client.get(
            f"/api/projects/{first['project_id']}/regulatory-context",
            params={
                "target_field_id": second["target_field_id"],
                "as_of": AS_OF.isoformat(),
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "target field does not belong to the authorized project"}


def test_http_build_does_not_mutate_authoritative_semantic_rows() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        before = _authoritative_snapshot(sessions)

        response = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context",
            params={
                "target_field_id": fixture["target_field_id"],
                "as_of": AS_OF.isoformat(),
            },
        )

        after = _authoritative_snapshot(sessions)

    assert response.status_code == 200, response.text
    assert after == before


@contextmanager
def _regulatory_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def override_get_db() -> Iterator[Session]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _seed_acceptance_target(
    sessions: sessionmaker,
    *,
    suffix: str = "A",
) -> dict[str, int]:
    with sessions() as db:
        institution = Institution(
            institution_code=f"CTX_API_BANK_{suffix}",
            institution_name=f"API 隔离银行 {suffix}",
        )
        db.add(institution)
        db.flush()
        project = Project(
            name=f"监管上下文 API 项目 {suffix}",
            bank_name=institution.institution_name,
            institution_id=institution.id,
        )
        db.add(project)
        db.flush()
        target_table = TargetTable(
            project_id=project.id,
            table_code="2.3",
            table_name="同业客户表",
            description="同业客户监管报送表",
        )
        db.add(target_table)
        db.flush()
        target_field = TargetField(
            project_id=project.id,
            target_table_id=target_table.id,
            field_code="CUST_UNIFIED_NO",
            field_name="客户统一编号",
            field_type="VARCHAR(64)",
            required_flag=True,
            field_definition="全行范围内唯一识别同业客户的编号",
            regulatory_description="报送同业客户唯一标识",
        )
        concept = SemanticConcept(
            project_id=project.id,
            institution_id=project.institution_id,
            concept_type="business_term",
            concept_code="CUST_UNIFIED_NO",
            concept_name="客户统一编号",
            definition="全行客户唯一标识",
            status="confirmed",
            confidence_level="high",
            confirmed_by="reviewer",
            confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        db.add_all([target_field, concept])
        db.flush()
        version = SemanticConceptVersion(
            semantic_concept_id=concept.id,
            project_id=project.id,
            institution_id=project.institution_id,
            version_no=1,
            concept_name="客户统一编号",
            definition="全行客户唯一标识",
            aliases_json=["统一客户号"],
            provenance_json={"source": "api-test"},
            status="confirmed",
            confidence_level="high",
            confirmed_by="reviewer",
            confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        binding = SemanticBinding(
            project_id=project.id,
            institution_id=project.institution_id,
            semantic_concept_id=concept.id,
            entity_type="target_field",
            entity_id=target_field.id,
            binding_type="represents",
            confidence_level="high",
            confidence_score=1.0,
            status="confirmed",
            confirmed_by="reviewer",
            confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        db.add_all([version, binding])
        db.commit()
        return {
            "project_id": project.id,
            "target_table_id": target_table.id,
            "target_field_id": target_field.id,
            "semantic_concept_id": concept.id,
            "semantic_version_id": version.id,
        }


def _authoritative_snapshot(sessions: sessionmaker) -> tuple[tuple[str, tuple], ...]:
    with sessions() as db:
        return tuple(
            (
                model.__tablename__,
                tuple(db.scalars(select(model.id).order_by(model.id)).all()),
            )
            for model in (
                Institution,
                Project,
                TargetTable,
                TargetField,
                SemanticConcept,
                SemanticConceptVersion,
                SemanticBinding,
            )
        )


def _contains_planning_requirement_ids(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_planning_requirement_ids(key)
            or _contains_planning_requirement_ids(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_planning_requirement_ids(item) for item in value)
    return value in {"CTX-01", "CTX-02", "CTX-03", "CTX-04"}
