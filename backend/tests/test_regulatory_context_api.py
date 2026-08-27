from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import regulatory_context as regulatory_context_api
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    BusinessSystem,
    HistoricalCaliberImport,
    HistoricalCaliberItem,
    Institution,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ProjectMembership,
    RegulatoryKnowledgeItem,
    RetrievalLog,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    SourceField,
    SourceTable,
    TargetField,
    TargetTable,
    User,
)
from app.schemas.regulatory_context import RegulatoryContext
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.permission_service import PermissionService
from app.services.retrieval.keyword_index import index_knowledge_unit
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


def test_large_persisted_mapping_evidence_is_truncated_instead_of_returning_400() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions, suffix="EVIDENCE_BUDGET")
        with sessions() as db:
            mapping = MartToYbtMapping(
                project_id=fixture["project_id"],
                target_field_id=fixture["target_field_id"],
                mapping_name="HTTP 大证据映射",
                mapping_status="approved",
                business_rule="直接映射",
                lineage_status="linked",
            )
            db.add(mapping)
            db.flush()
            mapping_id = int(mapping.id)
            db.add_all([
                MappingEvidenceReference(
                    project_id=fixture["project_id"],
                    mapping_type="mart_to_ybt",
                    mapping_id=mapping_id,
                    evidence_type="manual_note",
                    source_name=f"HTTP 证据 {index:02d}",
                    location_text=f"http-evidence:{index:02d}",
                    evidence_summary="验证有效持久化数据不会触发 400",
                )
                for index in range(51)
            ])
            db.commit()

        response = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context",
            params={
                "target_field_id": fixture["target_field_id"],
                "as_of": AS_OF.isoformat(),
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    mapping_payload = next(
        fact for fact in payload["mappings"]
        if fact["source_id"] == mapping_id
    )
    assert len(mapping_payload["evidence_references"]) == 50
    assert payload["build_metadata"]["truncated"] is True
    assert len(payload["build_metadata"]["warnings"]) == 1


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
    payload = response.json()
    assert payload["detail"] == "target field does not belong to the authorized project"
    assert payload["error_code"] == "invalid_request"
    assert payload["retryable"] is False


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


def test_all_contract_scope_parameters_and_bounds_are_enforced() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        fixture.update(_seed_optional_scope(sessions, fixture["project_id"]))
        response = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context",
            params={
                "target_table_id": fixture["target_table_id"],
                "target_field_id": fixture["target_field_id"],
                "scenario_id": fixture["scenario_id"],
                "mart_field_id": fixture["mart_field_id"],
                "semantic_concept_id": fixture["semantic_concept_id"],
                "as_of": AS_OF.isoformat(),
                "reporting_period": "2026 H1",
                "mode": "candidate",
                "candidate_limit": 7,
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        input_scope = payload["build_metadata"]["input_scope"]
        assert input_scope == {
            "reporting_period": "2026 H1",
            "mode": "candidate",
            "target_table_id": fixture["target_table_id"],
            "target_field_id": fixture["target_field_id"],
            "mart_field_id": fixture["mart_field_id"],
            "semantic_concept_id": fixture["semantic_concept_id"],
            "scenario_id": fixture["scenario_id"],
            "candidate_limit": 7,
        }
        assert payload["scenario"]["scenario_id"] == fixture["scenario_id"]

        invalid_params = [
            {"as_of": AS_OF.isoformat(), "target_table_id": 0},
            {"as_of": AS_OF.isoformat(), "target_field_id": -1},
            {"as_of": AS_OF.isoformat(), "scenario_id": 0},
            {"as_of": AS_OF.isoformat(), "mart_field_id": 0},
            {"as_of": AS_OF.isoformat(), "semantic_concept_id": 0},
            {"as_of": AS_OF.isoformat(), "candidate_limit": 0},
            {"as_of": AS_OF.isoformat(), "candidate_limit": 101},
            {"as_of": AS_OF.isoformat(), "mode": "audit"},
            {"as_of": "not-a-date"},
            {"as_of": AS_OF.isoformat(), "reporting_period": "R" * 121},
        ]
        for params in invalid_params:
            invalid = client.get(
                f"/api/projects/{fixture['project_id']}/regulatory-context",
                params=params,
            )
            assert invalid.status_code == 422, (params, invalid.text)

        missing_date = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context"
        )
        assert missing_date.status_code == 422


def test_two_institutions_with_identical_codes_remain_isolated() -> None:
    visible_marker = "VISIBLE_PROJECT_A_KNOWLEDGE"
    foreign_secret = "FOREIGN_PROJECT_B_SECRET"
    with _regulatory_client() as (client, sessions):
        first = _seed_acceptance_target(sessions, suffix="BANK_A")
        second = _seed_acceptance_target(sessions, suffix="BANK_B")
        _seed_knowledge_units(
            sessions,
            first["project_id"],
            start=0,
            count=1,
            marker=visible_marker,
            confidentiality="confidential",
        )
        _seed_knowledge_units(
            sessions,
            second["project_id"],
            start=100,
            count=1,
            marker=foreign_secret,
            confidentiality="restricted",
        )
        principal = _seed_project_viewer(sessions, first["project_id"])
        app.dependency_overrides[get_current_principal] = lambda: principal

        allowed = client.get(
            f"/api/projects/{first['project_id']}/regulatory-context",
            params={
                "target_field_id": first["target_field_id"],
                "as_of": AS_OF.isoformat(),
            },
        )
        hidden_project = client.get(
            f"/api/projects/{second['project_id']}/regulatory-context",
            params={
                "target_field_id": second["target_field_id"],
                "as_of": AS_OF.isoformat(),
            },
        )
        foreign_target = client.get(
            f"/api/projects/{first['project_id']}/regulatory-context",
            params={
                "target_field_id": second["target_field_id"],
                "as_of": AS_OF.isoformat(),
            },
        )

    assert allowed.status_code == 200, allowed.text
    assert visible_marker in allowed.text
    assert foreign_secret not in allowed.text
    assert hidden_project.status_code == 404
    assert foreign_secret not in hidden_project.text
    assert foreign_target.status_code == 400
    assert foreign_secret not in foreign_target.text
    payload = allowed.json()
    project_ids = {
        fact["provenance"]["project_id"]
        for section in (
            "semantic",
            "regulatory",
            "metadata",
            "candidates",
            "mappings",
            "lineage",
            "knowledge_evidence",
            "historical",
            "quality",
        )
        for fact in payload[section]
    }
    assert project_ids == {first["project_id"]}
    assert payload["scope"]["institution_id"] == first["institution_id"]
    assert payload["scope"]["institution_id"] != second["institution_id"]


def test_trusted_and_candidate_modes_preserve_lifecycle_and_provenance() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        lifecycle = _seed_lifecycle_concepts(sessions, fixture)
        path = f"/api/projects/{fixture['project_id']}/regulatory-context"
        params = {
            "target_field_id": fixture["target_field_id"],
            "as_of": AS_OF.isoformat(),
        }

        trusted = client.get(path, params=params)
        candidate = client.get(path, params={**params, "mode": "candidate"})

    assert trusted.status_code == 200, trusted.text
    assert candidate.status_code == 200, candidate.text
    trusted_payload = trusted.json()
    candidate_payload = candidate.json()
    assert {fact["source_id"] for fact in trusted_payload["semantic"]} == {
        fixture["semantic_version_id"]
    }
    assert trusted_payload["candidates"] == []

    candidate_ids = {
        fact["value"]["candidate_id"]
        for fact in candidate_payload["candidates"]
        if fact["value"]["candidate_type"] == "semantic_concept"
    }
    assert {lifecycle["draft"], lifecycle["ai_suggested"]} <= candidate_ids
    assert lifecycle["rejected"] not in candidate_ids
    assert lifecycle["deprecated"] not in candidate_ids
    for fact in candidate_payload["candidates"]:
        if (
            fact["value"]["candidate_type"] == "semantic_concept"
            and fact["value"]["candidate_id"] in candidate_ids
        ):
            assert fact["state"] != "confirmed"
            assert fact["source_type"] == "resolver_candidate"
            assert fact["provenance"]["source_model"] == "SemanticConcept"
            assert fact["provenance"]["project_id"] == fixture["project_id"]
    binding_candidates = [
        fact for fact in candidate_payload["candidates"]
        if fact["value"]["candidate_type"] == "semantic_binding"
    ]
    assert {fact["state"] for fact in binding_candidates} == {"draft", "ai_suggested"}
    assert all(
        fact["fact_type"] == "semantic_binding_candidate"
        and fact["source_id"] == fact["value"]["candidate_id"]
        and fact["provenance"]["source_model"] == "SemanticBinding"
        and fact["provenance"]["source_id"] == fact["source_id"]
        for fact in binding_candidates
    )


def test_inclusive_temporal_selection_and_overlap_are_stable_over_http() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        _seed_2027_version(sessions, fixture)
        path = f"/api/projects/{fixture['project_id']}/regulatory-context"
        common = {"target_field_id": fixture["target_field_id"]}

        final_2026 = client.get(
            path,
            params={**common, "as_of": "2026-12-31"},
        )
        first_2027 = client.get(
            path,
            params={**common, "as_of": "2027-01-01"},
        )
        _seed_overlapping_2027_version(sessions, fixture)
        overlap = client.get(
            path,
            params={**common, "as_of": "2027-06-30"},
        )

    assert final_2026.status_code == 200, final_2026.text
    assert final_2026.json()["semantic"][0]["version_no"] == 1
    assert first_2027.status_code == 200, first_2027.text
    assert first_2027.json()["semantic"][0]["version_no"] == 2
    assert first_2027.json()["semantic"][0]["value"]["definition"] == "2027 年监管口径"
    assert overlap.status_code == 409
    assert overlap.json()["detail"]["code"] == "SEMANTIC_VERSION_AMBIGUOUS"
    assert overlap.json()["detail"]["as_of"] == "2027-06-30"


def test_gap_conflict_and_open_question_codes_are_deterministic_http_data() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        _seed_regulatory_and_conflicting_history(sessions, fixture)
        path = f"/api/projects/{fixture['project_id']}/regulatory-context"
        params = {
            "target_field_id": fixture["target_field_id"],
            "as_of": AS_OF.isoformat(),
        }

        first = client.get(path, params=params)
        second = client.get(path, params=params)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_payload = first.json()
    second_payload = second.json()
    conflict_codes = [item["code"] for item in first_payload["conflicts"]]
    question_codes = [item["question_code"] for item in first_payload["open_questions"]]
    assert "CONFLICTING_AUTHORITATIVE_FACTS" in conflict_codes
    assert {
        "MISSING_SOURCE_MAPPING",
        "MISSING_MART_TO_YBT_MAPPING",
        "MISSING_LINEAGE",
        "MISSING_EVIDENCE",
    } <= set(question_codes)
    assert conflict_codes == [item["code"] for item in second_payload["conflicts"]]
    assert question_codes == [
        item["question_code"] for item in second_payload["open_questions"]
    ]
    assert not _contains_planning_requirement_ids(first_payload)


def test_empty_project_and_missing_knowledge_lineage_serialize_without_stubs() -> None:
    with _regulatory_client() as (client, sessions):
        project_id = _seed_empty_project(sessions)
        response = client.get(
            f"/api/projects/{project_id}/regulatory-context",
            params={"as_of": AS_OF.isoformat()},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["target"] == {
        "target_table_id": None,
        "target_field_id": None,
        "mart_field_id": None,
        "semantic_concept_id": None,
        "target_table_code": None,
        "target_table_name": None,
        "target_field_code": None,
        "target_field_name": None,
    }
    assert payload["semantic"] == []
    assert payload["mappings"] == []
    assert payload["lineage"] == []
    assert payload["knowledge_evidence"] == []
    assert payload["build_metadata"]["retrieval_log_ids"] == []
    assert {
        "MISSING_CONFIRMED_SEMANTIC_BINDING",
        "MISSING_CONFIRMED_SEMANTIC_VERSION",
        "MISSING_SOURCE_MAPPING",
        "MISSING_MART_TO_YBT_MAPPING",
        "MISSING_LINEAGE",
        "MISSING_KNOWLEDGE",
    } <= {item["question_code"] for item in payload["open_questions"]}


def test_long_text_and_large_retrieved_evidence_remain_bounded_and_traceable() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        with sessions() as db:
            version = db.get(SemanticConceptVersion, fixture["semantic_version_id"])
            version.definition = "定" * 13000
            db.commit()
        _seed_knowledge_units(
            sessions,
            fixture["project_id"],
            start=0,
            count=30,
            marker="LARGE_EVIDENCE",
            confidentiality="confidential",
            oversized=True,
        )

        response = client.get(
            f"/api/projects/{fixture['project_id']}/regulatory-context",
            params={
                "target_field_id": fixture["target_field_id"],
                "as_of": AS_OF.isoformat(),
                "candidate_limit": 100,
            },
        )
        payload = response.json()
        log_ids = payload["build_metadata"]["retrieval_log_ids"]
        with sessions() as db:
            persisted_logs = [db.get(RetrievalLog, log_id) for log_id in log_ids]

    assert response.status_code == 200, response.text
    assert len(payload["semantic"][0]["value"]["definition"]) == 12000
    assert payload["semantic"][0]["value"]["definition"].endswith("…")
    retrieved = [
        fact
        for fact in payload["knowledge_evidence"]
        if fact["fact_type"] == "retrieved_knowledge"
    ]
    assert len(retrieved) == 30
    assert all(len(fact["value"]["excerpt"]) <= 4000 for fact in retrieved)
    assert all(fact["state"] == "retrieved" for fact in retrieved)
    assert all(fact["provenance"]["retrieval_log_id"] in log_ids for fact in retrieved)
    assert all(fact["provenance"]["confidentiality_level"] == "confidential" for fact in retrieved)
    assert log_ids
    assert all(log is not None for log in persisted_logs)
    assert all(log.project_id == fixture["project_id"] for log in persisted_logs)
    assert all(log.final_result_count == 30 for log in persisted_logs)


def test_candidate_limit_and_http_query_budget_do_not_grow_with_rows() -> None:
    with _regulatory_client() as (client, sessions):
        fixture = _seed_acceptance_target(sessions)
        _seed_candidate_fields(sessions, fixture["project_id"], start=0, count=5)
        _seed_knowledge_units(
            sessions,
            fixture["project_id"],
            start=0,
            count=2,
            marker="BASELINE",
            confidentiality="internal",
        )
        path = f"/api/projects/{fixture['project_id']}/regulatory-context"
        params = {
            "target_field_id": fixture["target_field_id"],
            "as_of": AS_OF.isoformat(),
            "mode": "candidate",
            "candidate_limit": 3,
        }

        warmup = client.get(path, params=params)
        assert warmup.status_code == 200, warmup.text

        baseline, baseline_count = _count_request_statements(
            sessions.kw["bind"],
            client,
            path,
            params,
        )
        _seed_candidate_fields(sessions, fixture["project_id"], start=5, count=60)
        _seed_knowledge_units(
            sessions,
            fixture["project_id"],
            start=2,
            count=40,
            marker="GROWTH",
            confidentiality="internal",
        )
        growth, growth_count = _count_request_statements(
            sessions.kw["bind"],
            client,
            path,
            params,
        )

    assert baseline.status_code == 200, baseline.text
    assert growth.status_code == 200, growth.text
    assert len(baseline.json()["candidates"]) == 3
    assert len(growth.json()["candidates"]) == 3
    assert baseline_count > 0
    assert growth_count == baseline_count


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
            "institution_id": institution.id,
            "project_id": project.id,
            "target_table_id": target_table.id,
            "target_field_id": target_field.id,
            "semantic_concept_id": concept.id,
            "semantic_version_id": version.id,
        }


def _seed_optional_scope(
    sessions: sessionmaker,
    project_id: int,
) -> dict[str, int]:
    with sessions() as db:
        scenario = ProductScenario(
            project_id=project_id,
            scenario_code="CTX_API_SCENARIO",
            scenario_name="监管上下文 API 场景",
            scenario_type="regulatory_reporting",
            enabled=True,
        )
        mart_table = MartTable(
            project_id=project_id,
            table_code="CTX_API_MART",
            table_name="监管上下文集市表",
        )
        db.add_all([scenario, mart_table])
        db.flush()
        mart_field = MartField(
            project_id=project_id,
            mart_table_id=mart_table.id,
            field_code="CUST_UNIFIED_NO",
            field_name="集市客户统一编号",
            field_type="VARCHAR(64)",
            description="监管上下文可选集市字段",
        )
        db.add(mart_field)
        db.commit()
        return {"scenario_id": scenario.id, "mart_field_id": mart_field.id}


def _seed_project_viewer(sessions: sessionmaker, project_id: int) -> Principal:
    with sessions() as db:
        viewer = User(username=f"context_viewer_{project_id}")
        db.add(viewer)
        db.flush()
        db.add(ProjectMembership(
            project_id=project_id,
            user_id=viewer.id,
            project_role="viewer",
            status="active",
        ))
        db.commit()
        return Principal(viewer.id, viewer.username, None)


def _seed_lifecycle_concepts(
    sessions: sessionmaker,
    fixture: dict[str, int],
) -> dict[str, int]:
    with sessions() as db:
        project = db.get(Project, fixture["project_id"])
        result: dict[str, int] = {}
        for index, lifecycle in enumerate(
            ("draft", "ai_suggested", "rejected", "deprecated"),
            start=1,
        ):
            concept = SemanticConcept(
                project_id=project.id,
                institution_id=project.institution_id,
                concept_type="business_term",
                concept_code=f"CTX_API_{lifecycle.upper()}",
                concept_name=f"生命周期 {lifecycle}",
                definition=f"{lifecycle} 仅用于生命周期隔离测试",
                status=lifecycle,
                confidence_level="medium",
            )
            db.add(concept)
            db.flush()
            db.add(SemanticBinding(
                project_id=project.id,
                institution_id=project.institution_id,
                semantic_concept_id=concept.id,
                entity_type="target_field",
                entity_id=fixture["target_field_id"],
                binding_type=f"candidate_{index}",
                confidence_level="medium",
                confidence_score=0.5,
                status=lifecycle,
            ))
            result[lifecycle] = concept.id
        db.commit()
        return result


def _seed_2027_version(
    sessions: sessionmaker,
    fixture: dict[str, int],
) -> None:
    with sessions() as db:
        db.add(SemanticConceptVersion(
            semantic_concept_id=fixture["semantic_concept_id"],
            project_id=fixture["project_id"],
            institution_id=db.get(Project, fixture["project_id"]).institution_id,
            version_no=2,
            concept_name="客户统一编号",
            definition="2027 年监管口径",
            aliases_json=["统一客户号"],
            provenance_json={"source": "api-test-2027"},
            status="confirmed",
            confidence_level="high",
            confirmed_by="reviewer-2027",
            confirmed_at=datetime(2026, 12, 1, tzinfo=UTC),
            effective_from=date(2027, 1, 1),
            effective_to=None,
        ))
        db.commit()


def _seed_overlapping_2027_version(
    sessions: sessionmaker,
    fixture: dict[str, int],
) -> None:
    with sessions() as db:
        db.add(SemanticConceptVersion(
            semantic_concept_id=fixture["semantic_concept_id"],
            project_id=fixture["project_id"],
            institution_id=db.get(Project, fixture["project_id"]).institution_id,
            version_no=3,
            concept_name="客户统一编号冲突版本",
            definition="与 2027 版本重叠的监管口径",
            aliases_json=[],
            provenance_json={"source": "api-test-overlap"},
            status="confirmed",
            confidence_level="high",
            confirmed_by="overlap-reviewer",
            confirmed_at=datetime(2027, 5, 1, tzinfo=UTC),
            effective_from=date(2027, 6, 1),
            effective_to=date(2027, 12, 31),
        ))
        db.commit()


def _seed_regulatory_and_conflicting_history(
    sessions: sessionmaker,
    fixture: dict[str, int],
) -> None:
    with sessions() as db:
        project = db.get(Project, fixture["project_id"])
        target_table = db.get(TargetTable, fixture["target_table_id"])
        target_field = db.get(TargetField, fixture["target_field_id"])
        db.add(RegulatoryKnowledgeItem(
            project_id=project.id,
            knowledge_type="regulatory_qa",
            target_table_code=target_table.table_code,
            target_field_code=target_field.field_code,
            target_field_name=target_field.field_name,
            question_text="客户统一编号如何填报",
            regulatory_reply="客户统一编号应在全行范围唯一",
        ))
        historical_import = HistoricalCaliberImport(
            institution_id=project.institution_id,
            project_id=project.id,
            stored_file_id=1,
            import_name="API 历史冲突口径",
            document_type="full_package",
            status="parsed",
        )
        db.add(historical_import)
        db.flush()
        db.add(HistoricalCaliberItem(
            project_id=project.id,
            historical_import_id=historical_import.id,
            target_table_code=target_table.table_code,
            target_field_code=target_field.field_code,
            target_field_name=target_field.field_name,
            business_content="与当前确认语义完全矛盾的历史定义",
            source_sheet_name="历史口径",
            source_cell_range="A2:Z2",
            content_hash=("api-history" + "0" * 64)[:64],
            match_status="matched",
            matched_target_field_id=target_field.id,
        ))
        db.commit()


def _seed_empty_project(sessions: sessionmaker) -> int:
    with sessions() as db:
        institution = Institution(
            institution_code="CTX_API_EMPTY_BANK",
            institution_name="API 空项目银行",
        )
        db.add(institution)
        db.flush()
        project = Project(
            name="监管上下文空项目",
            bank_name=institution.institution_name,
            institution_id=institution.id,
        )
        db.add(project)
        db.commit()
        return project.id


def _seed_knowledge_units(
    sessions: sessionmaker,
    project_id: int,
    *,
    start: int,
    count: int,
    marker: str,
    confidentiality: str,
    oversized: bool = False,
) -> list[int]:
    with sessions() as db:
        document = KnowledgeDocument(
            project_id=project_id,
            file_name=f"context_{marker}_{start}.md",
            file_type="md",
            source_type="upload",
            storage_path=f"context/{marker}/{start}.md",
            knowledge_type="manual_note",
            knowledge_scope="project",
            document_status="indexed",
            confidentiality_level=confidentiality,
            current_version_no=1,
        )
        db.add(document)
        db.flush()
        version = KnowledgeDocumentVersion(
            project_id=project_id,
            document_id=document.id,
            version_no=1,
            file_name=document.file_name,
            storage_path=document.storage_path,
            file_hash=f"{project_id:08d}{start:08d}".ljust(64, "d"),
            parse_status="parsed",
        )
        db.add(version)
        db.flush()
        ids: list[int] = []
        for offset in range(count):
            sequence = start + offset
            suffix = " 据" * 2600 if oversized else ""
            content = (
                f"客户统一编号 CUST_UNIFIED_NO {marker}-{sequence} 来源字段规则"
                f"{suffix}"
            )
            unit = KnowledgeUnit(
                project_id=project_id,
                document_id=document.id,
                document_version_id=version.id,
                knowledge_type="manual_note",
                knowledge_scope="project",
                unit_type="paragraph",
                title=f"客户统一编号知识 {marker}-{sequence}",
                content=content,
                normalized_content=content.lower(),
                source_file_name=document.file_name,
                source_sheet_name="知识页",
                source_cell_range=f"A{sequence + 1}:B{sequence + 1}",
                target_table_code="2.3",
                target_field_code="CUST_UNIFIED_NO",
                target_field_name="客户统一编号",
                confidentiality_level=confidentiality,
                enabled=True,
                content_hash=f"{project_id:08d}{sequence:08d}".ljust(64, "c"),
            )
            db.add(unit)
            db.flush()
            index_knowledge_unit(db, unit)
            ids.append(unit.id)
        db.commit()
        return ids


def _seed_candidate_fields(
    sessions: sessionmaker,
    project_id: int,
    *,
    start: int,
    count: int,
) -> list[int]:
    with sessions() as db:
        source_table = db.scalar(select(SourceTable).where(
            SourceTable.project_id == project_id,
            SourceTable.table_code == "CTX_API_CANDIDATES",
        ))
        if source_table is None:
            system = BusinessSystem(
                project_id=project_id,
                system_code="CTX_API_SOURCE",
                system_name="监管上下文候选来源系统",
                enabled=True,
            )
            db.add(system)
            db.flush()
            source_table = SourceTable(
                project_id=project_id,
                business_system_id=system.id,
                table_code="CTX_API_CANDIDATES",
                table_name="监管上下文候选来源表",
            )
            db.add(source_table)
            db.flush()
        ids: list[int] = []
        for offset in range(count):
            sequence = start + offset
            field = SourceField(
                project_id=project_id,
                source_table_id=source_table.id,
                field_code=f"CTX_CANDIDATE_{sequence:03d}",
                field_name=f"候选客户字段 {sequence:03d}",
                field_comment="客户统一编号的候选来源字段",
            )
            db.add(field)
            db.flush()
            ids.append(field.id)
        db.commit()
        return ids


def _count_request_statements(
    engine: object,
    client: TestClient,
    path: str,
    params: dict[str, object],
) -> tuple[object, int]:
    count = 0

    def before_cursor_execute(*args: object, **kwargs: object) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        response = client.get(path, params=params)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return response, count


def _authoritative_snapshot(sessions: sessionmaker) -> tuple[tuple[str, tuple], ...]:
    with sessions() as db:
        return (
            (
                "institutions",
                tuple(db.execute(select(
                    Institution.id,
                    Institution.institution_code,
                    Institution.institution_name,
                ).order_by(Institution.id)).all()),
            ),
            (
                "projects",
                tuple(db.execute(select(
                    Project.id,
                    Project.institution_id,
                    Project.name,
                    Project.bank_name,
                    Project.confidentiality_level,
                ).order_by(Project.id)).all()),
            ),
            (
                "target_tables",
                tuple(db.execute(select(
                    TargetTable.id,
                    TargetTable.project_id,
                    TargetTable.table_code,
                    TargetTable.table_name,
                    TargetTable.description,
                ).order_by(TargetTable.id)).all()),
            ),
            (
                "target_fields",
                tuple(db.execute(select(
                    TargetField.id,
                    TargetField.project_id,
                    TargetField.target_table_id,
                    TargetField.field_code,
                    TargetField.field_name,
                    TargetField.field_definition,
                    TargetField.regulatory_description,
                ).order_by(TargetField.id)).all()),
            ),
            (
                "semantic_concepts",
                tuple(db.execute(select(
                    SemanticConcept.id,
                    SemanticConcept.project_id,
                    SemanticConcept.institution_id,
                    SemanticConcept.concept_code,
                    SemanticConcept.concept_name,
                    SemanticConcept.definition,
                    SemanticConcept.status,
                    SemanticConcept.confirmed_by,
                    SemanticConcept.confirmed_at,
                ).order_by(SemanticConcept.id)).all()),
            ),
            (
                "semantic_concept_versions",
                tuple(db.execute(select(
                    SemanticConceptVersion.id,
                    SemanticConceptVersion.semantic_concept_id,
                    SemanticConceptVersion.project_id,
                    SemanticConceptVersion.version_no,
                    SemanticConceptVersion.concept_name,
                    SemanticConceptVersion.definition,
                    SemanticConceptVersion.status,
                    SemanticConceptVersion.effective_from,
                    SemanticConceptVersion.effective_to,
                ).order_by(SemanticConceptVersion.id)).all()),
            ),
            (
                "semantic_bindings",
                tuple(db.execute(select(
                    SemanticBinding.id,
                    SemanticBinding.project_id,
                    SemanticBinding.semantic_concept_id,
                    SemanticBinding.entity_type,
                    SemanticBinding.entity_id,
                    SemanticBinding.binding_type,
                    SemanticBinding.status,
                    SemanticBinding.confidence_level,
                    SemanticBinding.confidence_score,
                ).order_by(SemanticBinding.id)).all()),
            ),
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
