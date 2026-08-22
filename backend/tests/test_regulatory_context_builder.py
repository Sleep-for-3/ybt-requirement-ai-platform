from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Institution,
    Project,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    TargetField,
    TargetTable,
)
from app.schemas.regulatory_context import ContextMode, RegulatoryContext, RegulatoryContextRequest
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.semantic import context_builder as context_builder_module
from app.services.semantic.context_authority import FactState, authority_for_source
from app.services.semantic.context_builder import RegulatoryContextBuilder


AS_OF = date(2026, 6, 30)


def test_acceptance_context_build_returns_typed_project_scoped_date_effective_facts(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = _authorized_project(db_session, fixture["project_id"])
    request = RegulatoryContextRequest(
        project_id=project.id,
        target_table_id=fixture["target_table_id"],
        target_field_id=fixture["target_field_id"],
        as_of=AS_OF,
        reporting_period=" 2026   H1 ",
    )

    context = RegulatoryContextBuilder(db_session).build(
        request,
        authorized_project=project,
    )

    assert isinstance(context, RegulatoryContext)
    assert context.context_schema_version == "1.0"
    assert context.scope.project_id == project.id
    assert context.scope.institution_id == project.institution_id
    assert context.scope.as_of == AS_OF
    assert context.scope.reporting_period == "2026 H1"
    assert context.target.target_table_code == "2.3"
    assert context.target.target_table_name == "同业客户表"
    assert context.target.target_field_name == "客户统一编号"
    assert [fact.value.semantic_concept_version_id for fact in context.semantic] == [
        fixture["semantic_version_id"]
    ]
    assert context.semantic[0].effective_period.effective_from == date(2026, 1, 1)
    assert context.semantic[0].state is FactState.CONFIRMED
    assert context.metadata
    assert all(fact.authority is authority_for_source(fact.source_type) for fact in _all_facts(context))
    assert context.build_metadata.project_id == project.id
    assert context.build_metadata.input_scope.target_field_id == fixture["target_field_id"]


def test_authorized_project_mismatch_is_rejected_before_collectors(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    other = _seed_project(db_session, "CTX_BANK_B", "隔离银行 B", "隔离项目 B")
    authorized_project = _authorized_project(db_session, fixture["project_id"])
    collector_called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal collector_called
        collector_called = True
        raise AssertionError("collector must not run for mismatched project scope")

    monkeypatch.setattr(context_builder_module, "collect_base_context", fail_if_called)

    with pytest.raises(ValueError, match="authorized project"):
        RegulatoryContextBuilder(db_session).build(
            RegulatoryContextRequest(project_id=other.id, as_of=AS_OF),
            authorized_project=authorized_project,
        )

    assert collector_called is False


def test_projection_only_build_preserves_authoritative_rows(db_session: Session) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = _authorized_project(db_session, fixture["project_id"])
    request = RegulatoryContextRequest(
        project_id=project.id,
        target_field_id=fixture["target_field_id"],
        as_of=AS_OF,
    )
    before = _authoritative_snapshot(db_session, project.id)

    RegulatoryContextBuilder(db_session).build(request, authorized_project=project)

    assert _authoritative_snapshot(db_session, project.id) == before


def test_repeat_builds_preserve_domain_content_and_validate_volatile_metadata(
    db_session: Session,
) -> None:
    fixture = _seed_acceptance_target(db_session)
    project = _authorized_project(db_session, fixture["project_id"])
    request = RegulatoryContextRequest(
        project_id=project.id,
        target_table_id=fixture["target_table_id"],
        target_field_id=fixture["target_field_id"],
        semantic_concept_id=fixture["semantic_concept_id"],
        as_of=AS_OF,
        mode=ContextMode.TRUSTED,
    )
    builder = RegulatoryContextBuilder(db_session)

    first = builder.build(request, authorized_project=project)
    second = builder.build(request, authorized_project=project)

    assert _stable_projection(first) == _stable_projection(second)
    for context in (first, second):
        assert context.build_metadata.built_at.tzinfo is not None
        assert context.build_metadata.built_at.utcoffset() is not None
        assert context.build_metadata.retrieval_log_ids == []
        assert context.conflicts == sorted(
            context.conflicts,
            key=lambda item: item.deterministic_sort_key(),
        )
        assert context.open_questions == sorted(
            context.open_questions,
            key=lambda item: item.deterministic_sort_key(),
        )


def _seed_acceptance_target(db: Session) -> dict[str, int]:
    project = _seed_project(db, "CTX_BANK_A", "隔离银行 A", "监管上下文项目 A")
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


def _seed_project(db: Session, code: str, bank_name: str, project_name: str) -> Project:
    institution = Institution(institution_code=code, institution_name=bank_name)
    db.add(institution)
    db.flush()
    project = Project(
        name=project_name,
        bank_name=bank_name,
        institution_id=institution.id,
    )
    db.add(project)
    db.flush()
    return project


def _authorized_project(db: Session, project_id: int) -> Project:
    principal = Principal(None, "legacy-system", "Legacy development mode", True)
    return PermissionService(db, principal).require_project_permission(project_id, "project.view")


def _all_facts(context: RegulatoryContext) -> list:
    return [
        *context.semantic,
        *context.regulatory,
        *context.metadata,
        *context.candidates,
        *context.mappings,
        *context.lineage,
        *context.knowledge_evidence,
        *context.historical,
        *context.quality,
    ]


def _authoritative_snapshot(db: Session, project_id: int) -> tuple[tuple[str, int], ...]:
    models = (TargetField, SemanticConcept, SemanticConceptVersion, SemanticBinding)
    return tuple(
        (model.__tablename__, int(db.scalar(select(func.count()).select_from(model).where(model.project_id == project_id))))
        for model in models
    )


def _stable_projection(context: RegulatoryContext) -> dict:
    payload = deepcopy(context.model_dump(mode="json"))
    payload["build_metadata"]["built_at"] = "<volatile-built-at>"
    payload["build_metadata"]["retrieval_log_ids"] = ["<volatile-retrieval-log-id>"] * len(
        payload["build_metadata"]["retrieval_log_ids"]
    )
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
    ):
        for fact in payload[section]:
            if fact["provenance"]["retrieval_log_id"] is not None:
                fact["provenance"]["retrieval_log_id"] = "<volatile-retrieval-log-id>"
    return payload
