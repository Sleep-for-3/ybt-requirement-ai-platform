import asyncio
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    BackgroundJob,
    BackgroundJobItem,
    DeliverablePackage,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ProjectMembership,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.mapping import scenario_draft_generator
from app.services.mapping.context_adapters import (
    PHYSICAL_SOURCE_EVIDENCE_MISSING,
    ScenarioPhysicalCoverageAudit,
    ScenarioTechnicalProjection,
)
from app.services.mapping.generation_readiness import GenerationReadiness
from app.services.mapping.generator_context import (
    GenerationActorError,
    GenerationBlockedError,
    GenerationStaleError,
)
from app.api import deliverables, jobs, scenario_mappings


def test_business_generate_route_passes_exact_authorized_context_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "business-route") as (db, _, fixture):
        actor = _principal(fixture)
        captured: list[dict[str, object]] = []
        editability_calls: list[tuple[str, int]] = []

        def editable_spy(session: Session, mapping_type: str, mapping_id: int) -> None:
            assert session is db
            editability_calls.append((mapping_type, mapping_id))

        async def fake_generate(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None = None,
            today_provider=date.today,
        ) -> ScenarioBusinessMapping:
            captured.append({
                "session": session,
                "mapping_id": mapping_id,
                "authorized_project": authorized_project,
                "actor": actor,
                "as_of": as_of,
                "today_provider": today_provider,
            })
            return fixture["mapping"]

        monkeypatch.setattr(scenario_mappings, "ensure_scenario_mapping_editable", editable_spy)
        monkeypatch.setattr(scenario_mappings, "generate_business_draft", fake_generate)

        selected_date = date(2026, 6, 30)
        result = asyncio.run(
            scenario_mappings.generate_scenario_business_draft(
                fixture["mapping"].id,
                principal=actor,
                as_of=selected_date,
                db=db,
            )
        )
        assert result.id == fixture["mapping"].id
        assert captured[-1]["actor"] is actor
        assert captured[-1]["authorized_project"] is fixture["project"]
        assert captured[-1]["as_of"] == selected_date
        assert editability_calls == [("scenario_business", fixture["mapping"].id)]

        asyncio.run(
            scenario_mappings.generate_scenario_business_draft(
                fixture["mapping"].id,
                principal=actor,
                as_of=None,
                db=db,
            )
        )
        assert captured[-1]["as_of"] is None

        explicit_legacy = Principal(None, "legacy-system", "Legacy", True)
        asyncio.run(
            scenario_mappings.generate_scenario_business_draft(
                fixture["mapping"].id,
                principal=explicit_legacy,
                as_of=None,
                db=db,
            )
        )
        assert captured[-1]["actor"] is explicit_legacy

        with pytest.raises(HTTPException) as invalid:
            asyncio.run(
                scenario_mappings.generate_scenario_business_draft(
                    fixture["mapping"].id,
                    principal=Principal(None, "falsey", None, False),
                    as_of=None,
                    db=db,
                )
            )
        assert invalid.value.status_code in {401, 403}


def test_business_generate_uses_context_preserves_final_and_questions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "business-context") as (db, _, fixture):
        actor = _principal(fixture)
        calls = {"context": 0, "model": 0}

        def fake_build(*args, **kwargs):
            calls["context"] += 1
            assert kwargs["authorized_project"] is fixture["project"]
            assert kwargs["actor"] is actor
            assert kwargs["explicit_as_of"] == date(2026, 6, 30)
            return _business_context_envelope(snapshot=kwargs["snapshot"])

        async def fake_model(*args, **kwargs):
            calls["model"] += 1
            assert args[2].prompt_key == "scenario_business_mapping"
            assert args[4].__name__ == "ScenarioBusinessOutput"
            return {
                "business_definition": "受治理的 AI 业务定义",
                "business_owner": "AI 建议负责人",
                "open_questions": ["模型问题"],
                "confidence_level": "high",
                "final_content_draft": "受治理的场景业务草稿",
                "business_confirm_status": "confirmed",
            }

        monkeypatch.setattr(scenario_draft_generator, "build_generation_context", fake_build)
        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", fake_model)
        before = _business_mapping_state(fixture["mapping"])

        generated = asyncio.run(
            scenario_draft_generator.generate_business_draft(
                db,
                fixture["mapping"].id,
                authorized_project=fixture["project"],
                actor=actor,
                as_of=date(2026, 6, 30),
            )
        )

        assert calls == {"context": 1, "model": 1}
        assert generated.final_content == before[2]
        assert generated.business_confirm_status == before[3]
        assert generated.open_questions.startswith("人工业务问题保持原样")
        assert "[CTX:MISSING_EVIDENCE]" in generated.open_questions
        assert "[AI] 模型问题" in generated.open_questions
        assert generated.confidence_level == "low"
        assert generated.ai_generated_content == "受治理的场景业务草稿"
        audit = db.scalar(select(AuditLog).where(
            AuditLog.action == "generate_business_draft",
            AuditLog.resource_id == str(generated.id),
        ))
        assert audit is not None
        assert audit.result == "success"
        assert audit.after_summary_json["resolved_as_of"] == "2026-06-30"
        assert "受治理的场景业务草稿" not in str(audit.after_summary_json)

        source = inspect.getsource(scenario_draft_generator.generate_business_draft)
        for forbidden in (
            "HybridRetriever",
            "MappingEvidenceReference",
            "TargetField",
            "ProductScenario",
            "__dict__",
        ):
            assert forbidden not in source


def test_business_generate_blocks_or_fails_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "business-failure") as (db, _, fixture):
        actor = _principal(fixture)
        before = _business_mapping_state(fixture["mapping"])

        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _business_context_envelope(
                snapshot=kwargs["snapshot"],
                can_generate=False,
            ),
        )

        async def forbidden_model(*args, **kwargs):
            raise AssertionError("blocked business generation reached the model")

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", forbidden_model)
        with pytest.raises(GenerationBlockedError, match="CONFLICTING_AUTHORITATIVE_FACTS"):
            asyncio.run(
                scenario_draft_generator.generate_business_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=actor,
                )
            )
        db.expire_all()
        assert _business_mapping_state(db.get(ScenarioBusinessMapping, fixture["mapping"].id)) == before

        def builder_failure(*args, **kwargs):
            raise RuntimeError("Context unavailable")

        monkeypatch.setattr(scenario_draft_generator, "build_generation_context", builder_failure)
        with pytest.raises(RuntimeError, match="Context unavailable"):
            asyncio.run(
                scenario_draft_generator.generate_business_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=actor,
                )
            )
        db.rollback()
        db.expire_all()
        assert _business_mapping_state(db.get(ScenarioBusinessMapping, fixture["mapping"].id)) == before


def test_business_generate_rejects_concurrent_final_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "business-stale") as (db, factory, fixture):
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _business_context_envelope(snapshot=kwargs["snapshot"]),
        )

        async def mutate_final_during_model(*args, **kwargs):
            with factory() as concurrent:
                current = concurrent.get(ScenarioBusinessMapping, fixture["mapping"].id)
                current.final_content = "并发人工最终内容"
                concurrent.commit()
            return {
                "business_definition": "不应落库的模型定义",
                "open_questions": ["不应落库的问题"],
                "confidence_level": "high",
            }

        monkeypatch.setattr(
            scenario_draft_generator,
            "execute_runtime_chat",
            mutate_final_during_model,
        )
        old_draft = fixture["mapping"].ai_generated_content
        with pytest.raises(GenerationStaleError) as stale:
            asyncio.run(
                scenario_draft_generator.generate_business_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        assert "task.final_content" in stale.value.changed_fields
        with factory() as verify:
            current = verify.get(ScenarioBusinessMapping, fixture["mapping"].id)
            assert current.final_content == "并发人工最终内容"
            assert current.ai_generated_content == old_draft
            assert verify.scalar(select(AuditLog.id).where(
                AuditLog.action == "generate_business_draft",
                AuditLog.result == "success",
            )) is None


def test_business_generate_revalidates_actor_and_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "business-actor") as (db, factory, fixture):
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _business_context_envelope(snapshot=kwargs["snapshot"]),
        )

        async def disable_actor(*args, **kwargs):
            with factory() as concurrent:
                current = concurrent.get(User, fixture["user"].id)
                current.status = "disabled"
                concurrent.commit()
            return {"business_definition": "不应落库", "confidence_level": "high"}

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", disable_actor)
        with pytest.raises(GenerationActorError, match="active User"):
            asyncio.run(
                scenario_draft_generator.generate_business_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        with factory() as verify:
            assert verify.get(ScenarioBusinessMapping, fixture["mapping"].id).ai_generated_content == "旧业务 AI 草稿"

    with _scenario_service_session(tmp_path, "business-permission") as (db, factory, fixture):
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _business_context_envelope(snapshot=kwargs["snapshot"]),
        )

        async def revoke_permission(*args, **kwargs):
            with factory() as concurrent:
                membership = concurrent.get(ProjectMembership, fixture["membership"].id)
                membership.project_role = "viewer"
                concurrent.commit()
            return {"business_definition": "不应落库", "confidence_level": "high"}

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", revoke_permission)
        with pytest.raises(HTTPException) as denied:
            asyncio.run(
                scenario_draft_generator.generate_business_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        assert denied.value.status_code == 403
        with factory() as verify:
            current = verify.get(ScenarioBusinessMapping, fixture["mapping"].id)
            assert current.ai_generated_content == "旧业务 AI 草稿"
            assert verify.scalar(select(AuditLog.id).where(
                AuditLog.action == "generate_business_draft",
                AuditLog.result == "success",
            )) is None


def test_technical_generate_route_passes_exact_authorized_context_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "technical-route") as (db, _, fixture):
        actor = _principal(fixture)
        captured: list[dict[str, object]] = []
        editability_calls: list[tuple[str, int]] = []

        def editable_spy(session: Session, mapping_type: str, mapping_id: int) -> None:
            assert session is db
            editability_calls.append((mapping_type, mapping_id))

        async def fake_generate(
            session: Session,
            lineage_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None = None,
            today_provider=date.today,
        ) -> ScenarioTechnicalLineage:
            captured.append({
                "session": session,
                "lineage_id": lineage_id,
                "authorized_project": authorized_project,
                "actor": actor,
                "as_of": as_of,
                "today_provider": today_provider,
            })
            return fixture["lineage"]

        monkeypatch.setattr(scenario_mappings, "ensure_scenario_mapping_editable", editable_spy)
        monkeypatch.setattr(scenario_mappings, "generate_technical_draft", fake_generate)

        selected_date = date(2026, 6, 30)
        result = asyncio.run(
            scenario_mappings.generate_scenario_technical_draft(
                fixture["lineage"].id,
                principal=actor,
                as_of=selected_date,
                db=db,
            )
        )
        assert result.id == fixture["lineage"].id
        assert captured[-1]["actor"] is actor
        assert captured[-1]["authorized_project"] is fixture["project"]
        assert captured[-1]["as_of"] == selected_date
        assert editability_calls == [("scenario_technical", fixture["lineage"].id)]

        explicit_legacy = Principal(None, "legacy-system", "Legacy", True)
        asyncio.run(
            scenario_mappings.generate_scenario_technical_draft(
                fixture["lineage"].id,
                principal=explicit_legacy,
                as_of=None,
                db=db,
            )
        )
        assert captured[-1]["actor"] is explicit_legacy

        with pytest.raises(HTTPException) as invalid:
            asyncio.run(
                scenario_mappings.generate_scenario_technical_draft(
                    fixture["lineage"].id,
                    principal=Principal(None, "falsey", None, False),
                    as_of=None,
                    db=db,
                )
            )
        assert invalid.value.status_code in {401, 403}


def test_technical_generate_accepts_exact_context_physical_tuple(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "technical-allowed") as (db, _, fixture):
        actor = _principal(fixture)
        allowed = ("trusted_db", "ods", "trusted_table", "trusted_field")
        calls = {"context": 0, "model": 0}

        def fake_build(*args, **kwargs):
            calls["context"] += 1
            assert kwargs["authorized_project"] is fixture["project"]
            assert kwargs["actor"] is actor
            assert kwargs["explicit_as_of"] == date(2026, 6, 30)
            return _technical_context_envelope(
                snapshot=kwargs["snapshot"],
                whitelist=(allowed,),
            )

        async def fake_model(*args, **kwargs):
            calls["model"] += 1
            assert args[2].prompt_key == "scenario_technical_lineage"
            assert args[4].__name__ == "ScenarioTechnicalOutput"
            return {
                "source_system_name": "受治理的系统建议",
                "source_database_name": "TRUSTED_DB",
                "source_schema_name": "ODS",
                "source_table_english_name": "TRUSTED_TABLE",
                "source_field_english_name": "TRUSTED_FIELD",
                "processing_logic": "受治理的安全处理逻辑",
                "processing_logic_type": "direct",
                "open_questions": ["模型技术问题"],
                "confidence_level": "high",
                "final_content_draft": "受治理的场景技术草稿",
                "tech_confirm_status": "confirmed",
            }

        monkeypatch.setattr(scenario_draft_generator, "build_generation_context", fake_build)
        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", fake_model)
        before = _technical_lineage_state(fixture["lineage"])

        generated = asyncio.run(
            scenario_draft_generator.generate_technical_draft(
                db,
                fixture["lineage"].id,
                authorized_project=fixture["project"],
                actor=actor,
                as_of=date(2026, 6, 30),
            )
        )

        assert calls == {"context": 1, "model": 1}
        assert generated.final_content == before[4]
        assert generated.tech_confirm_status == before[5]
        assert (
            generated.source_database_name.casefold(),
            generated.source_schema_name.casefold(),
            generated.source_table_english_name.casefold(),
            generated.source_field_english_name.casefold(),
        ) == allowed
        assert generated.processing_logic == "受治理的安全处理逻辑"
        assert generated.open_questions.startswith("人工技术问题保持原样")
        assert "[AI] 模型技术问题" in generated.open_questions
        assert generated.ai_generated_content == "受治理的场景技术草稿"
        assert generated.confidence_level == "high"
        audit = db.scalar(select(AuditLog).where(
            AuditLog.action == "generate_technical_draft",
            AuditLog.resource_id == str(generated.id),
        ))
        assert audit is not None
        assert audit.result == "success"
        assert audit.after_summary_json["resolved_as_of"] == "2026-06-30"
        assert "受治理的场景技术草稿" not in str(audit.after_summary_json)

        source = inspect.getsource(scenario_draft_generator.generate_technical_draft)
        for forbidden in (
            "HybridRetriever",
            "MappingEvidenceReference",
            "CatalogColumn",
            "TargetField",
            "ProductScenario",
            "__dict__",
            "_physical_value_allowed",
        ):
            assert forbidden not in source


def test_technical_generate_skips_unknown_physical_tuple_but_keeps_safe_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "technical-unknown") as (db, _, fixture):
        allowed = ("trusted_db", "ods", "trusted_table", "trusted_field")
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _technical_context_envelope(
                snapshot=kwargs["snapshot"],
                whitelist=(allowed,),
            ),
        )

        async def unknown_physical(*args, **kwargs):
            return {
                "source_database_name": "foreign_db",
                "source_schema_name": "foreign_schema",
                "source_table_english_name": "foreign_table",
                "source_field_english_name": "foreign_field",
                "processing_logic": "仍可采用的安全处理逻辑",
                "confidence_level": "high",
                "final_content_draft": "不含证据原文的技术草稿",
            }

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", unknown_physical)
        before = _technical_lineage_state(fixture["lineage"])
        generated = asyncio.run(
            scenario_draft_generator.generate_technical_draft(
                db,
                fixture["lineage"].id,
                authorized_project=fixture["project"],
                actor=_principal(fixture),
            )
        )

        assert _technical_physical_tuple(generated) == before[:4]
        assert generated.processing_logic == "仍可采用的安全处理逻辑"
        assert generated.confidence_level == "low"
        assert f"[CTX:{PHYSICAL_SOURCE_EVIDENCE_MISSING}]" in generated.open_questions
        assert generated.final_content == before[4]
        assert generated.tech_confirm_status == before[5]


def test_technical_generate_appends_only_frozen_context_evidence_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "technical-evidence") as (db, _, fixture):
        marker = "PROFILE_EVIDENCE total=4; null_rate=0.25; distinct=2"
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _technical_context_envelope(
                snapshot=kwargs["snapshot"],
                supporting_evidence_summaries=(marker,),
            ),
        )

        async def safe_model(*args, **kwargs):
            assert marker in args[3]
            return {
                "processing_logic": "按已确认探查指标生成保守技术草稿",
                "confidence_level": "medium",
                "final_content_draft": "受治理的技术草稿",
            }

        monkeypatch.setattr(
            scenario_draft_generator,
            "execute_runtime_chat",
            safe_model,
        )
        original_final = fixture["lineage"].final_content
        original_status = fixture["lineage"].tech_confirm_status

        generated = asyncio.run(
            scenario_draft_generator.generate_technical_draft(
                db,
                fixture["lineage"].id,
                authorized_project=fixture["project"],
                actor=_principal(fixture),
            )
        )

        assert generated.ai_generated_content == (
            "受治理的技术草稿\n\n目录字段与安全探查摘要：\n" + marker
        )
        assert generated.final_content == original_final
        assert generated.tech_confirm_status == original_status
        audit = db.scalar(select(AuditLog).where(
            AuditLog.action == "generate_technical_draft",
            AuditLog.resource_id == str(generated.id),
        ))
        assert audit is not None
        assert marker not in str(audit.after_summary_json)


def test_technical_generate_blocks_or_rejects_concurrent_physical_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "technical-blocked") as (db, _, fixture):
        before = _technical_lineage_state(fixture["lineage"])
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _technical_context_envelope(
                snapshot=kwargs["snapshot"],
                can_generate=False,
            ),
        )

        async def forbidden_model(*args, **kwargs):
            raise AssertionError("blocked technical generation reached the model")

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", forbidden_model)
        with pytest.raises(GenerationBlockedError, match="CONFLICTING_AUTHORITATIVE_FACTS"):
            asyncio.run(
                scenario_draft_generator.generate_technical_draft(
                    db,
                    fixture["lineage"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        db.expire_all()
        assert _technical_lineage_state(
            db.get(ScenarioTechnicalLineage, fixture["lineage"].id)
        ) == before

    with _scenario_service_session(tmp_path, "technical-stale") as (db, factory, fixture):
        allowed = ("trusted_db", "ods", "trusted_table", "trusted_field")
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _technical_context_envelope(
                snapshot=kwargs["snapshot"],
                whitelist=(allowed,),
            ),
        )

        async def mutate_physical_during_model(*args, **kwargs):
            with factory() as concurrent:
                current = concurrent.get(ScenarioTechnicalLineage, fixture["lineage"].id)
                current.source_database_name = "并发人工数据库"
                concurrent.commit()
            return {
                "source_database_name": "trusted_db",
                "source_schema_name": "ods",
                "source_table_english_name": "trusted_table",
                "source_field_english_name": "trusted_field",
                "processing_logic": "不应落库的模型逻辑",
                "confidence_level": "high",
            }

        monkeypatch.setattr(
            scenario_draft_generator,
            "execute_runtime_chat",
            mutate_physical_during_model,
        )
        old_draft = fixture["lineage"].ai_generated_content
        with pytest.raises(GenerationStaleError) as stale:
            asyncio.run(
                scenario_draft_generator.generate_technical_draft(
                    db,
                    fixture["lineage"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        assert "task.source_database_name" in stale.value.changed_fields
        with factory() as verify:
            current = verify.get(ScenarioTechnicalLineage, fixture["lineage"].id)
            assert current.source_database_name == "并发人工数据库"
            assert current.ai_generated_content == old_draft
            assert verify.scalar(select(AuditLog.id).where(
                AuditLog.action == "generate_technical_draft",
                AuditLog.result == "success",
            )) is None


def test_technical_generate_revalidates_actor_and_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "technical-actor") as (db, factory, fixture):
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _technical_context_envelope(snapshot=kwargs["snapshot"]),
        )

        async def disable_actor(*args, **kwargs):
            with factory() as concurrent:
                current = concurrent.get(User, fixture["user"].id)
                current.status = "disabled"
                concurrent.commit()
            return {"processing_logic": "不应落库", "confidence_level": "high"}

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", disable_actor)
        with pytest.raises(GenerationActorError, match="active User"):
            asyncio.run(
                scenario_draft_generator.generate_technical_draft(
                    db,
                    fixture["lineage"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        with factory() as verify:
            assert verify.get(ScenarioTechnicalLineage, fixture["lineage"].id).ai_generated_content == "旧技术 AI 草稿"

    with _scenario_service_session(tmp_path, "technical-permission") as (db, factory, fixture):
        monkeypatch.setattr(
            scenario_draft_generator,
            "build_generation_context",
            lambda *args, **kwargs: _technical_context_envelope(snapshot=kwargs["snapshot"]),
        )

        async def revoke_permission(*args, **kwargs):
            with factory() as concurrent:
                membership = concurrent.get(ProjectMembership, fixture["membership"].id)
                membership.project_role = "viewer"
                concurrent.commit()
            return {"processing_logic": "不应落库", "confidence_level": "high"}

        monkeypatch.setattr(scenario_draft_generator, "execute_runtime_chat", revoke_permission)
        with pytest.raises(HTTPException) as denied:
            asyncio.run(
                scenario_draft_generator.generate_technical_draft(
                    db,
                    fixture["lineage"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        assert denied.value.status_code == 403
        with factory() as verify:
            current = verify.get(ScenarioTechnicalLineage, fixture["lineage"].id)
            assert current.ai_generated_content == "旧技术 AI 草稿"
            assert verify.scalar(select(AuditLog.id).where(
                AuditLog.action == "generate_technical_draft",
                AuditLog.result == "success",
            )) is None


def test_batch_queued_handlers_recover_exact_nonlegacy_actor_and_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "batch-context") as (db, _, fixture):
        captures: list[tuple[str, Project, Principal, date | None]] = []

        async def fake_business(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None,
        ) -> ScenarioBusinessMapping:
            assert session is db
            assert mapping_id == fixture["mapping"].id
            captures.append(("business", authorized_project, actor, as_of))
            return fixture["mapping"]

        async def fake_technical(
            session: Session,
            lineage_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None,
        ) -> ScenarioTechnicalLineage:
            assert session is db
            assert lineage_id == fixture["lineage"].id
            captures.append(("technical", authorized_project, actor, as_of))
            return fixture["lineage"]

        monkeypatch.setattr(jobs, "generate_business_draft", fake_business)
        monkeypatch.setattr(jobs, "generate_technical_draft", fake_technical)
        monkeypatch.setattr(jobs, "notify_user", lambda *args, **kwargs: None)
        business_job = _seed_background_job(
            db,
            fixture,
            "batch-business-context",
            "batch_ai_generation_business",
        )
        technical_job = _seed_background_job(
            db,
            fixture,
            "batch-technical-context",
            "batch_ai_generation_technical",
        )

        business_result = jobs._business_handler(db, business_job)
        technical_result = jobs._technical_handler(db, technical_job)

        assert business_result == {
            "success_count": 1,
            "failed_count": 0,
            "blocked_count": 0,
            "total_count": 1,
        }
        assert technical_result == {
            "success_count": 1,
            "failed_count": 0,
            "blocked_count": 0,
            "total_count": 1,
        }
        assert [item[0] for item in captures] == ["business", "technical"]
        for _, authorized_project, actor, as_of in captures:
            assert authorized_project is fixture["project"]
            assert actor == Principal(
                fixture["user"].id,
                fixture["user"].username,
                fixture["user"].display_name,
                False,
            )
            assert actor.is_legacy_system is False
            assert as_of is None


@pytest.mark.parametrize("invalid_creator", [None, 0, 999_999])
def test_batch_queued_handler_blocks_invalid_creator_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_creator: int | None,
) -> None:
    with _scenario_service_session(tmp_path, f"batch-invalid-{invalid_creator}") as (db, _, fixture):
        called = 0

        async def forbidden_generator(*args, **kwargs):
            nonlocal called
            called += 1
            raise AssertionError("invalid queued identity reached generator")

        monkeypatch.setattr(jobs, "notify_user", lambda *args, **kwargs: None)
        persisted = _seed_background_job(
            db,
            fixture,
            f"batch-invalid-{invalid_creator}",
            "batch_ai_generation_business",
        )
        queued_view = SimpleNamespace(
            id=persisted.id,
            project_id=persisted.project_id,
            institution_id=persisted.institution_id,
            created_by=invalid_creator,
            payload_summary_json={},
            status="running",
        )

        result = jobs._draft_handler(
            db,
            queued_view,
            ScenarioBusinessMapping,
            forbidden_generator,
        )

        assert called == 0
        assert result == {
            "success_count": 0,
            "failed_count": 0,
            "blocked_count": 1,
            "total_count": 1,
        }
        item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == persisted.id,
            BackgroundJobItem.item_key == str(fixture["mapping"].id),
        ))
        assert item is not None
        assert item.status == "blocked"
        assert item.result_summary_json == {
            "mapping_id": fixture["mapping"].id,
            "reason_code": "queued_actor_invalid",
        }
        assert item.error_message == "queued_actor_invalid"


def test_batch_queued_handler_blocks_disabled_creator_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "batch-disabled") as (db, _, fixture):
        job = _seed_background_job(
            db,
            fixture,
            "batch-disabled",
            "batch_ai_generation_technical",
        )
        fixture["user"].status = "disabled"
        db.commit()
        monkeypatch.setattr(jobs, "notify_user", lambda *args, **kwargs: None)

        async def forbidden_generator(*args, **kwargs):
            raise AssertionError("disabled queued identity reached generator")

        result = jobs._draft_handler(
            db,
            job,
            ScenarioTechnicalLineage,
            forbidden_generator,
        )

        assert result["blocked_count"] == 1
        assert result["success_count"] == result["failed_count"] == 0
        item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == job.id,
        ))
        assert item.status == "blocked"
        assert item.error_message == "queued_actor_invalid"


def test_batch_runtime_failure_is_bounded_to_one_background_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "batch-runtime") as (db, _, fixture):
        before = _business_mapping_state(fixture["mapping"])
        job = _seed_background_job(
            db,
            fixture,
            "batch-runtime",
            "batch_ai_generation_business",
        )
        monkeypatch.setattr(jobs, "notify_user", lambda *args, **kwargs: None)

        async def runtime_failure(*args, **kwargs):
            raise RuntimeError("private prompt and evidence must not enter job summaries")

        result = jobs._draft_handler(
            db,
            job,
            ScenarioBusinessMapping,
            runtime_failure,
        )

        assert result == {
            "success_count": 0,
            "failed_count": 1,
            "blocked_count": 0,
            "total_count": 1,
        }
        item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == job.id,
        ))
        assert item.status == "failed"
        assert item.result_summary_json == {
            "mapping_id": fixture["mapping"].id,
            "reason_code": "generation_failed",
        }
        assert item.error_message == "generation_failed"
        assert "private prompt" not in str(item.result_summary_json)
        db.expire_all()
        assert _business_mapping_state(
            db.get(ScenarioBusinessMapping, fixture["mapping"].id)
        ) == before


def test_deliverable_queued_handler_passes_scoped_context_and_counts_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "deliverable-context") as (db, _, fixture):
        package, job = _seed_deliverable_job(db, fixture, "deliverable-context")
        mart_table = MartTable(
            project_id=fixture["project"].id,
            table_code="MART_DELIVERABLE_CONTEXT",
            table_name="交付集市表",
        )
        db.add(mart_table)
        db.flush()
        mart_field = MartField(
            project_id=fixture["project"].id,
            mart_table_id=mart_table.id,
            field_code="MART_DELIVERABLE_FIELD",
            field_name="交付集市字段",
        )
        db.add(mart_field)
        db.flush()
        source_mapping = SourceToMartMapping(
            project_id=fixture["project"].id,
            mart_field_id=mart_field.id,
            mapping_status="draft",
        )
        mart_mapping = MartToYbtMapping(
            project_id=fixture["project"].id,
            target_field_id=fixture["target_field"].id,
            mart_field_id=mart_field.id,
            mapping_status="draft",
        )
        db.add_all([source_mapping, mart_mapping])
        db.commit()
        captures: list[tuple[str, Project, Principal, date | None]] = []

        async def fake_business(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None,
        ) -> ScenarioBusinessMapping:
            captures.append(("business", authorized_project, actor, as_of))
            return session.get(ScenarioBusinessMapping, mapping_id)

        async def fake_technical(
            session: Session,
            lineage_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None,
        ) -> ScenarioTechnicalLineage:
            captures.append(("technical", authorized_project, actor, as_of))
            return session.get(ScenarioTechnicalLineage, lineage_id)

        async def fake_source(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None,
        ) -> SourceToMartMapping:
            captures.append(("source", authorized_project, actor, as_of))
            mapping = session.get(SourceToMartMapping, mapping_id)
            mapping.ai_generated_content = "Governed queued Source draft"
            return mapping

        async def fake_mart(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None,
        ) -> MartToYbtMapping:
            captures.append(("mart", authorized_project, actor, as_of))
            mapping = session.get(MartToYbtMapping, mapping_id)
            mapping.ai_generated_content = "Governed queued Mart draft"
            return mapping

        _isolate_deliverable_generation(monkeypatch)
        monkeypatch.setattr(deliverables, "generate_business_draft", fake_business)
        monkeypatch.setattr(deliverables, "generate_technical_draft", fake_technical)
        monkeypatch.setattr(deliverables, "generate_source_to_mart_draft", fake_source, raising=False)
        monkeypatch.setattr(deliverables, "generate_mart_to_ybt_draft", fake_mart, raising=False)
        result = deliverables._deliverable_generate_handler(db, job)

        assert result["success_count"] == 1
        assert result["failed_count"] == result["blocked_count"] == 0
        assert [item[0] for item in captures] == ["business", "technical", "source", "mart"]
        for _, authorized_project, actor, as_of in captures:
            assert authorized_project is fixture["project"]
            assert actor == _principal(fixture)
            assert actor.is_legacy_system is False
            assert as_of is None
        assert db.get(DeliverablePackage, package.id).status == "draft"
        source_item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == job.id,
            BackgroundJobItem.item_key == f"source_to_mart:{source_mapping.id}",
        ))
        mart_item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == job.id,
            BackgroundJobItem.item_key == f"mart_to_ybt:{mart_mapping.id}",
        ))
        assert source_item.status == mart_item.status == "completed"

    with _scenario_service_session(tmp_path, "deliverable-blocked") as (db, _, fixture):
        _, job = _seed_deliverable_job(db, fixture, "deliverable-blocked")
        fixture["lineage"].ai_generated_content = "已有技术 AI 草稿"
        db.commit()

        async def readiness_block(*args, **kwargs):
            raise GenerationBlockedError(["CONFLICTING_AUTHORITATIVE_FACTS"])

        _isolate_deliverable_generation(monkeypatch)
        monkeypatch.setattr(deliverables, "generate_business_draft", readiness_block)

        result = deliverables._deliverable_generate_handler(db, job)

        assert result["failed_count"] == 0
        assert result["blocked_count"] == 1
        item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == job.id,
            BackgroundJobItem.item_key == f"business:{fixture['mapping'].id}",
        ))
        assert item is not None
        assert item.status == "blocked"
        assert item.result_summary_json == {
            "mapping_id": fixture["mapping"].id,
            "reason_code": "generation_readiness_blocked",
        }
        assert item.error_message == "generation_readiness_blocked"


def test_deliverable_queued_handler_blocks_disabled_actor_before_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "deliverable-disabled") as (db, _, fixture):
        package, job = _seed_deliverable_job(db, fixture, "deliverable-disabled")
        fixture["user"].status = "disabled"
        db.commit()
        _isolate_deliverable_generation(monkeypatch)

        async def forbidden_generator(*args, **kwargs):
            raise AssertionError("disabled Deliverable actor reached generator")

        monkeypatch.setattr(deliverables, "generate_business_draft", forbidden_generator)
        monkeypatch.setattr(deliverables, "generate_technical_draft", forbidden_generator)

        result = deliverables._deliverable_generate_handler(db, job)

        assert result["success_count"] == result["failed_count"] == 0
        assert result["blocked_count"] == 1
        assert db.get(DeliverablePackage, package.id).status == "draft"
        item = db.scalar(select(BackgroundJobItem).where(
            BackgroundJobItem.background_job_id == job.id,
            BackgroundJobItem.item_key == f"package:{package.id}",
        ))
        assert item.status == "blocked"
        assert item.result_summary_json["reason_code"] == "queued_actor_invalid"
        assert item.error_message == "queued_actor_invalid"


def test_deliverable_source_and_mart_items_block_when_technical_permission_is_revoked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _scenario_service_session(tmp_path, "deliverable-mapping-revoked") as (db, _, fixture):
        _, job = _seed_deliverable_job(db, fixture, "deliverable-mapping-revoked")
        fixture["mapping"].ai_generated_content = "已有业务草稿"
        fixture["lineage"].ai_generated_content = "已有技术草稿"
        mart_table = MartTable(
            project_id=fixture["project"].id,
            table_code="MART_REVOKED",
            table_name="撤权集市表",
        )
        db.add(mart_table)
        db.flush()
        mart_field = MartField(
            project_id=fixture["project"].id,
            mart_table_id=mart_table.id,
            field_code="MART_REVOKED_FIELD",
            field_name="撤权集市字段",
        )
        db.add(mart_field)
        db.flush()
        source_mapping = SourceToMartMapping(
            project_id=fixture["project"].id,
            mart_field_id=mart_field.id,
            mapping_status="draft",
        )
        mart_mapping = MartToYbtMapping(
            project_id=fixture["project"].id,
            target_field_id=fixture["target_field"].id,
            mart_field_id=mart_field.id,
            mapping_status="draft",
        )
        db.add_all([source_mapping, mart_mapping])
        db.commit()

        _isolate_deliverable_generation(monkeypatch)
        calls = {"source": 0, "mart": 0}

        def revoke_after_package_authorization(*args, **kwargs):
            fixture["membership"].project_role = "business_analyst"
            db.commit()
            return []

        async def forbidden_source(*args, **kwargs):
            calls["source"] += 1
            raise AssertionError("revoked actor reached Source generator")

        async def forbidden_mart(*args, **kwargs):
            calls["mart"] += 1
            raise AssertionError("revoked actor reached Mart generator")

        monkeypatch.setattr(deliverables, "build_lineage_records", revoke_after_package_authorization)
        monkeypatch.setattr(deliverables, "generate_source_to_mart_draft", forbidden_source)
        monkeypatch.setattr(deliverables, "generate_mart_to_ybt_draft", forbidden_mart)

        result = deliverables._deliverable_generate_handler(db, job)

        assert result["failed_count"] == 0
        assert result["blocked_count"] == 1
        assert calls == {"source": 0, "mart": 0}
        for item_key in (
            f"source_to_mart:{source_mapping.id}",
            f"mart_to_ybt:{mart_mapping.id}",
        ):
            item = db.scalar(select(BackgroundJobItem).where(
                BackgroundJobItem.background_job_id == job.id,
                BackgroundJobItem.item_key == item_key,
            ))
            assert item.status == "blocked"
            assert item.result_summary_json["reason_code"] == "generation_permission_denied"
            assert item.error_message == "generation_permission_denied"
        db.expire_all()
        assert db.get(SourceToMartMapping, source_mapping.id).ai_generated_content is None
        assert db.get(MartToYbtMapping, mart_mapping.id).ai_generated_content is None


def test_product_scenario_crud_and_project_code_uniqueness() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "场景口径项目"})
        scenario = _post(
            client,
            f"/api/projects/{project['id']}/scenarios",
            {
                "scenario_code": "DEBIT_CARD",
                "scenario_name": "借记卡",
                "scenario_type": "product",
                "business_owner": "银行卡部",
                "tech_owner": "信息科技部",
                "sort_order": 10,
            },
        )

        assert scenario["scenario_code"] == "DEBIT_CARD"
        assert scenario["enabled"] is True
        listed = _get(client, f"/api/projects/{project['id']}/scenarios")
        assert [item["scenario_name"] for item in listed] == ["借记卡"]

        updated = _put(client, f"/api/scenarios/{scenario['id']}", {"scenario_name": "借记卡业务", "enabled": False})
        assert updated["scenario_name"] == "借记卡业务"
        assert updated["enabled"] is False

        duplicate = client.post(
            f"/api/projects/{project['id']}/scenarios",
            json={"scenario_code": "DEBIT_CARD", "scenario_name": "重复场景"},
        )
        assert duplicate.status_code == 409

        deleted = client.delete(f"/api/scenarios/{scenario['id']}")
        deleted.raise_for_status()
        assert deleted.json() == {"status": "deleted"}


def test_scenario_mappings_adopt_drafts_quality_checks_and_knowledge_search() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "字段场景项目"})
        table = _post(
            client,
            "/api/target-tables",
            {"project_id": project["id"], "table_code": "YBT_CARD", "table_name": "银行卡信息"},
        )
        field = _post(
            client,
            "/api/fields",
            {
                "project_id": project["id"],
                "target_table_id": table["id"],
                "field_code": "CARD_PRODUCT_ID",
                "field_name": "卡产品编号",
                "field_definition": "银行卡产品唯一编号",
            },
        )
        scenario = _post(
            client,
            f"/api/projects/{project['id']}/scenarios",
            {"scenario_code": "DEBIT_CARD", "scenario_name": "借记卡"},
        )

        business = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/business-mapping",
            {"business_definition": "取借记卡产品编号", "business_owner": "银行卡部"},
        )
        lineage = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/technical-lineage",
            {
                "business_mapping_id": business["id"],
                "source_system_name": "借记卡系统",
                "source_table_english_name": "CPS_CARDPRODUCT",
                "source_field_english_name": "CARD_PRODUCT_ID",
                "processing_logic": "源字段直接取值",
                "processing_logic_type": "direct",
            },
        )
        assert business["business_confirm_status"] == "draft"
        assert lineage["processing_logic_type"] == "direct"

        business_with_draft = _put(
            client,
            f"/api/scenario-business-mappings/{business['id']}",
            {"final_content": "人工业务口径"},
        )
        generated_business = _post(client, f"/api/scenario-business-mappings/{business['id']}/generate-draft", {})
        adopted_business = _post(
            client,
            f"/api/scenario-business-mappings/{business['id']}/adopt-ai-draft",
            {},
        )
        assert business_with_draft["final_content"] == "人工业务口径"
        assert generated_business["final_content"] == "人工业务口径"
        assert generated_business["ai_generated_content"]
        assert adopted_business["final_content"] == generated_business["ai_generated_content"]

        lineage_with_draft = _put(
            client,
            f"/api/scenario-technical-lineages/{lineage['id']}",
            {"final_content": "人工技术口径"},
        )
        generated_lineage = _post(client, f"/api/scenario-technical-lineages/{lineage['id']}/generate-draft", {})
        adopted_lineage = _post(
            client,
            f"/api/scenario-technical-lineages/{lineage['id']}/adopt-ai-draft",
            {},
        )
        assert lineage_with_draft["final_content"] == "人工技术口径"
        assert generated_lineage["final_content"] == "人工技术口径"
        assert generated_lineage["ai_generated_content"]
        assert adopted_lineage["final_content"] == generated_lineage["ai_generated_content"]

        empty_business = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id'] + 1}/business-mapping",
            {},
            expected_status=404,
        )
        assert empty_business["detail"] == "Scenario not found"

        assert client.post(f"/api/scenario-business-mappings/{business['id']}/confirm", json={}).status_code == 400
        assert client.post(f"/api/scenario-technical-lineages/{lineage['id']}/confirm", json={}).status_code == 400
        _post(client, f"/api/mappings/scenario_business/{business['id']}/evidence", {
            "evidence_type": "manual_note", "source_name": "脱敏业务访谈记录", "evidence_summary": "业务部门已确认"
        })
        _post(client, f"/api/mappings/scenario_technical/{lineage['id']}/evidence", {
            "evidence_type": "manual_note", "source_name": "脱敏技术访谈记录", "evidence_summary": "科技部门已确认"
        })
        confirmed_business = _post(client, f"/api/scenario-business-mappings/{business['id']}/confirm", {"confirmed_by": "tester"})
        confirmed_lineage = _post(client, f"/api/scenario-technical-lineages/{lineage['id']}/confirm", {"confirmed_by": "tester"})
        assert confirmed_business["business_confirm_status"] == "confirmed"
        assert confirmed_lineage["tech_confirm_status"] == "confirmed"

        pending_scenario = _post(
            client,
            f"/api/projects/{project['id']}/scenarios",
            {"scenario_code": "PENDING", "scenario_name": "待确认场景"},
        )
        empty_business = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{pending_scenario['id']}/business-mapping",
            {},
        )
        empty_lineage = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{pending_scenario['id']}/technical-lineage",
            {},
        )
        assert client.post(f"/api/scenario-business-mappings/{empty_business['id']}/confirm", json={}).status_code == 400
        assert client.post(f"/api/scenario-technical-lineages/{empty_lineage['id']}/confirm", json={}).status_code == 400
        invalid_business_status = client.put(
            f"/api/scenario-business-mappings/{empty_business['id']}",
            json={"business_confirm_status": "approved_without_review"},
        )
        invalid_tech_status = client.put(
            f"/api/scenario-technical-lineages/{empty_lineage['id']}",
            json={"tech_confirm_status": "approved_without_review"},
        )
        assert invalid_business_status.status_code == 422
        assert invalid_tech_status.status_code == 422
        assert client.put(
            f"/api/scenario-business-mappings/{empty_business['id']}",
            json={"business_confirm_status": "confirmed"},
        ).status_code == 422
        assert client.put(
            f"/api/scenario-technical-lineages/{empty_lineage['id']}",
            json={"tech_confirm_status": "confirmed"},
        ).status_code == 422

        knowledge = _post(
            client,
            f"/api/projects/{project['id']}/knowledge/items",
            {
                "knowledge_type": "historical_mapping",
                "target_table_code": "YBT_CARD",
                "target_field_code": "CARD_PRODUCT_ID",
                "target_field_name": "卡产品编号",
                "scenario_id": scenario["id"],
                "business_explanation": "历史确认从借记卡系统产品表取值",
                "source_document_name": "脱敏历史口径.xlsx",
                "source_sheet_name": "银行卡信息",
                "source_cell_range": "L3",
            },
        )
        search = _post(
            client,
            f"/api/projects/{project['id']}/knowledge/search",
            {"target_field_code": "CARD_PRODUCT_ID", "scenario_id": scenario["id"], "query": "借记卡", "top_k": 5},
        )
        assert knowledge["knowledge_type"] == "historical_mapping"
        assert search["items"][0]["id"] == knowledge["id"]
        assert search["items"][0]["score"] > 0


def test_source_recommendations_are_scored_explained_and_selected_explicitly() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "来源推荐项目"})
        table = _post(client, "/api/target-tables", {
            "project_id": project["id"], "table_code": "YBT_CARD", "table_name": "银行卡信息"
        })
        field = _post(client, "/api/fields", {
            "project_id": project["id"], "target_table_id": table["id"], "field_code": "CARD_PRODUCT_ID",
            "field_name": "卡产品编号", "field_definition": "银行卡产品唯一编号"
        })
        scenario = _post(client, f"/api/projects/{project['id']}/scenarios", {
            "scenario_code": "DEBIT_CARD", "scenario_name": "借记卡"
        })
        unrelated_system = _post(client, f"/api/projects/{project['id']}/business-systems", {
            "system_code": "OTHER", "system_name": "无关系统"
        })
        unrelated_table = _post(client, f"/api/business-systems/{unrelated_system['id']}/source-tables", {
            "table_code": "OTHER_TABLE", "table_name": "无关表"
        })
        unrelated_source = _post(client, f"/api/source-tables/{unrelated_table['id']}/source-fields", {
            "field_code": "UNRELATED_VALUE", "field_name": "无关字段", "field_comment": "与卡产品无关"
        })
        card_system = _post(client, f"/api/projects/{project['id']}/business-systems", {
            "system_code": "DCPS", "system_name": "借记卡系统"
        })
        card_table = _post(client, f"/api/business-systems/{card_system['id']}/source-tables", {
            "table_code": "CPS_CARDPRODUCT", "table_name": "卡产品表", "schema_name": "ODS"
        })
        source = _post(client, f"/api/source-tables/{card_table['id']}/source-fields", {
            "field_code": "CARD_PRODUCT_ID", "field_name": "卡产品编号", "field_comment": "银行卡产品唯一编号"
        })
        _post(client, f"/api/projects/{project['id']}/knowledge/items", {
            "knowledge_type": "historical_mapping", "target_field_code": "CARD_PRODUCT_ID", "scenario_id": scenario["id"],
            "business_explanation": "借记卡场景历史来源为 CPS_CARDPRODUCT.CARD_PRODUCT_ID"
        })
        other_field = _post(client, "/api/fields", {
            "project_id": project["id"], "target_table_id": table["id"], "field_code": "OTHER_TARGET",
            "field_name": "其他目标字段",
        })
        other_mapping = _post(
            client,
            f"/api/target-fields/{other_field['id']}/scenarios/{scenario['id']}/business-mapping",
            {"business_definition": "其他字段业务定义"},
        )
        _post(client, f"/api/mappings/scenario_business/{other_mapping['id']}/evidence", {
            "evidence_type": "source_field", "evidence_id": unrelated_source["id"],
            "source_name": "无关场景绑定", "evidence_summary": "只属于其他目标字段",
        })

        response = _post(client, f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/recommend-sources", {})
        top = response["recommendations"][0]
        assert top["recommended_field_name"] == source["field_code"]
        assert top["score"] > response["recommendations"][-1]["score"]
        assert top["recommend_reason"]
        assert "场景匹配" in top["recommend_reason"]
        assert top["evidence_summary"]
        assert top["selected_flag"] is False
        unrelated_recommendation = next(
            item for item in response["recommendations"] if item["recommended_field_name"] == unrelated_source["field_code"]
        )
        assert "已绑定人工证据" not in unrelated_recommendation["recommend_reason"]

        selected = _post(client, f"/api/source-recommendations/{top['id']}/select", {})
        assert selected["recommendation"]["selected_flag"] is True
        assert selected["lineage"]["source_system_name"] == "借记卡系统"
        assert selected["lineage"]["source_table_english_name"] == "CPS_CARDPRODUCT"
        assert selected["lineage"]["source_field_english_name"] == "CARD_PRODUCT_ID"
        assert selected["lineage"]["final_content"] is None


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _post(client: TestClient, path: str, payload: dict, expected_status: int = 200) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code == expected_status, response.text
    return response.json()


def _put(client: TestClient, path: str, payload: dict) -> dict:
    response = client.put(path, json=payload)
    response.raise_for_status()
    return response.json()


def _get(client: TestClient, path: str) -> dict | list[dict]:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


@contextmanager
def _scenario_service_session(
    tmp_path: Path,
    suffix: str,
) -> Iterator[tuple[Session, sessionmaker, dict[str, object]]]:
    database_path = tmp_path / f"scenario-{suffix}.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    fixture = _seed_business_mapping(db, suffix)
    try:
        yield db, factory, fixture
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_business_mapping(db: Session, suffix: str) -> dict[str, object]:
    user = User(
        username=f"scenario-generator-{suffix}",
        display_name=f"Scenario Generator {suffix}",
        status="active",
    )
    project = Project(
        name=f"Scenario generator {suffix}",
        project_status="active",
        confidentiality_level="internal",
        governance_workflow_enabled=True,
    )
    db.add_all([user, project])
    db.flush()
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        project_role="project_manager",
        status="active",
    )
    target_table = TargetTable(
        project_id=project.id,
        table_code=f"YBT_{suffix.upper()}",
        table_name="场景目标表",
    )
    scenario = ProductScenario(
        project_id=project.id,
        scenario_code=f"SCENARIO_{suffix.upper()}",
        scenario_name="借记卡",
        enabled=True,
    )
    db.add_all([membership, target_table, scenario])
    db.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code=f"FIELD_{suffix.upper()}",
        field_name="场景目标字段",
        field_definition="人工监管字段定义",
    )
    db.add(target_field)
    db.flush()
    mapping = ScenarioBusinessMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        scenario_id=scenario.id,
        business_definition="人工原业务定义",
        source_system_screenshot_required=True,
        source_system_change_required=False,
        external_data_required=False,
        manual_supplement_required=True,
        business_owner="人工业务负责人",
        business_confirm_status="draft",
        remarks="人工备注",
        ai_generated_content="旧业务 AI 草稿",
        final_content="人工最终业务口径",
        confidence_level="medium",
        open_questions="人工业务问题保持原样",
        created_by=user.username,
    )
    db.add(mapping)
    db.flush()
    lineage = ScenarioTechnicalLineage(
        project_id=project.id,
        target_field_id=target_field.id,
        scenario_id=scenario.id,
        business_mapping_id=mapping.id,
        source_system_name="人工原系统",
        source_database_name="current_db",
        source_schema_name="current_schema",
        source_table_english_name="current_table",
        source_table_chinese_name="人工原表",
        source_field_english_name="current_field",
        source_field_chinese_name="人工原字段",
        processing_logic="人工原处理逻辑",
        processing_logic_type="direct",
        tech_owner="人工技术负责人",
        tech_confirm_status="draft",
        remarks="人工技术备注",
        ai_generated_content="旧技术 AI 草稿",
        final_content="人工最终技术口径",
        confidence_level="medium",
        open_questions="人工技术问题保持原样",
        created_by=user.username,
        lineage_status="verified",
    )
    db.add(lineage)
    db.commit()
    for row in (user, project, membership, target_table, target_field, scenario, mapping, lineage):
        db.refresh(row)
    return {
        "user": user,
        "project": project,
        "membership": membership,
        "target_table": target_table,
        "target_field": target_field,
        "scenario": scenario,
        "mapping": mapping,
        "lineage": lineage,
    }


def _principal(fixture: dict[str, object]) -> Principal:
    user = fixture["user"]
    return Principal(user.id, user.username, user.display_name, False)


def _business_context_envelope(
    *,
    snapshot: object,
    can_generate: bool = True,
) -> SimpleNamespace:
    blocking = [] if can_generate else ["CONFLICTING_AUTHORITATIVE_FACTS"]
    context_questions = [
        SimpleNamespace(
            question_code="MISSING_EVIDENCE",
            question_text="请补充业务证据。",
            priority="high",
            target_type="scenario_business",
            target_id=1,
            resolution_state="open",
        )
    ]
    projection = SimpleNamespace(
        task_type="scenario_business",
        prompt_text="受治理的 Scenario business Context 投影",
        confidentiality_levels=["internal"],
        context_questions=context_questions,
        readiness=SimpleNamespace(
            can_generate=can_generate,
            blocking_reasons=blocking,
            warnings=["MISSING_EVIDENCE"],
            confidence_cap="low",
        ),
    )
    trace_values = {
        "context_schema_version": "1.0",
        "context_built_at": "2026-06-30T00:00:00+00:00",
        "resolved_as_of": "2026-06-30",
        "as_of_source": "explicit",
        "context_fact_count": 1,
        "context_conflict_codes": blocking,
        "context_question_codes": ["MISSING_EVIDENCE"],
        "retrieval_log_ids": [301],
        "readiness_can_generate": can_generate,
        "readiness_confidence_cap": "low",
        "prompt_projection_hash": "c" * 64,
        "prompt_projection_truncated": False,
    }
    return SimpleNamespace(
        snapshot=snapshot,
        projection=projection,
        trace=SimpleNamespace(
            retrieval_log_ids=[301],
            model_dump=lambda **kwargs: dict(trace_values),
        ),
    )


def _business_mapping_state(mapping: ScenarioBusinessMapping) -> tuple[object, ...]:
    return (
        mapping.business_definition,
        mapping.open_questions,
        mapping.final_content,
        mapping.business_confirm_status,
        mapping.ai_generated_content,
        mapping.confidence_level,
        mapping.business_owner,
        mapping.remarks,
    )


def _technical_context_envelope(
    *,
    snapshot: object,
    can_generate: bool = True,
    whitelist: tuple[tuple[str, str, str, str], ...] = (),
    supporting_evidence_summaries: tuple[str, ...] = (),
) -> SimpleNamespace:
    blocking = [] if can_generate else ["CONFLICTING_AUTHORITATIVE_FACTS"]
    questions = []
    readiness = GenerationReadiness(
        can_generate=can_generate,
        confidence_cap="high" if can_generate else "low",
        blocking_reasons=blocking,
        warnings=[],
    )
    current = (
        snapshot.task.source_database_name.casefold(),
        snapshot.task.source_schema_name.casefold(),
        snapshot.task.source_table_english_name.casefold(),
        snapshot.task.source_field_english_name.casefold(),
    )
    coverage = ScenarioPhysicalCoverageAudit(
        allowlisted_sources=whitelist,
        unchanged_current_source=current,
        catalog_evidence_count=len(whitelist),
        verified_lineage_count=0,
        warning=None,
        open_question=None,
        confidence_cap="high",
    )
    projection = ScenarioTechnicalProjection(
        prompt_text=(
            "受治理的 Scenario technical Context 投影\n"
            + "\n".join(supporting_evidence_summaries)
        ),
        confidentiality_levels=["internal"],
        selected_fact_refs=["metadata:catalog_column:1"],
        context_questions=questions,
        readiness=readiness,
        projection_hash="d" * 64,
        truncated=False,
        physical_whitelist=whitelist,
        physical_coverage=coverage,
        supporting_evidence_summaries=supporting_evidence_summaries,
    )
    trace_values = {
        "context_schema_version": "1.0",
        "context_built_at": "2026-06-30T00:00:00+00:00",
        "resolved_as_of": "2026-06-30",
        "as_of_source": "explicit",
        "context_fact_count": 1,
        "context_conflict_codes": blocking,
        "context_question_codes": [],
        "retrieval_log_ids": [302],
        "readiness_can_generate": can_generate,
        "readiness_confidence_cap": readiness.confidence_cap,
        "prompt_projection_hash": "d" * 64,
        "prompt_projection_truncated": False,
    }
    return SimpleNamespace(
        snapshot=snapshot,
        projection=projection,
        context=SimpleNamespace(scenario=SimpleNamespace(scenario_name="借记卡")),
        trace=SimpleNamespace(
            retrieval_log_ids=[302],
            model_dump=lambda **kwargs: dict(trace_values),
        ),
    )


def _technical_physical_tuple(
    lineage: ScenarioTechnicalLineage,
) -> tuple[object, object, object, object]:
    return (
        lineage.source_database_name,
        lineage.source_schema_name,
        lineage.source_table_english_name,
        lineage.source_field_english_name,
    )


def _technical_lineage_state(lineage: ScenarioTechnicalLineage) -> tuple[object, ...]:
    return (
        *_technical_physical_tuple(lineage),
        lineage.final_content,
        lineage.tech_confirm_status,
        lineage.ai_generated_content,
        lineage.processing_logic,
        lineage.confidence_level,
        lineage.open_questions,
        lineage.lineage_status,
        lineage.remarks,
    )


def _seed_background_job(
    db: Session,
    fixture: dict[str, object],
    suffix: str,
    job_type: str,
    *,
    payload: dict[str, object] | None = None,
) -> BackgroundJob:
    job = BackgroundJob(
        institution_id=fixture["project"].institution_id,
        project_id=fixture["project"].id,
        idempotency_key=f"scenario-{suffix}",
        job_type=job_type,
        status="running",
        progress=0,
        payload_summary_json=payload or {},
        result_summary_json={},
        created_by=fixture["user"].id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_deliverable_job(
    db: Session,
    fixture: dict[str, object],
    suffix: str,
) -> tuple[DeliverablePackage, BackgroundJob]:
    fixture["mapping"].final_content = None
    fixture["mapping"].ai_generated_content = None
    fixture["mapping"].business_confirm_status = "draft"
    fixture["lineage"].final_content = None
    fixture["lineage"].ai_generated_content = None
    fixture["lineage"].tech_confirm_status = "draft"
    fingerprint = "e" * 64
    package = DeliverablePackage(
        institution_id=fixture["project"].institution_id,
        project_id=fixture["project"].id,
        package_name=f"Scenario deliverable {suffix}",
        package_type="full_delivery_package",
        target_table_id=fixture["target_table"].id,
        template_version_id=1,
        status="generating",
        generation_fingerprint=fingerprint,
        created_by=fixture["user"].id,
    )
    db.add(package)
    db.flush()
    job = BackgroundJob(
        institution_id=fixture["project"].institution_id,
        project_id=fixture["project"].id,
        idempotency_key=f"scenario-deliverable-{suffix}",
        job_type="deliverable_generate_field_items",
        status="running",
        progress=0,
        payload_summary_json={
            "package_id": package.id,
            "generation_fingerprint_hash": fingerprint,
        },
        result_summary_json={},
        created_by=fixture["user"].id,
    )
    db.add(job)
    db.flush()
    package.generation_job_id = job.id
    db.commit()
    db.refresh(package)
    db.refresh(job)
    return package, job


def _isolate_deliverable_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deliverables,
        "build_lineage_records",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        deliverables,
        "build_change_impact_records",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        deliverables,
        "_sync_evidence_items",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        deliverables,
        "_ensure_generation_questions",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        deliverables,
        "field_readiness",
        lambda *args, **kwargs: {
            "status": "approved",
            "evidence_completeness": 1.0,
            "open_question_count": 0,
        },
    )
