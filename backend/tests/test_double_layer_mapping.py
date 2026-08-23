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
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import mapping_rules
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    MartField,
    MartTable,
    MartToYbtMapping,
    Project,
    ProjectMembership,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.mapping import source_to_mart_generator
from app.services.mapping import mart_to_ybt_generator
from app.services.mapping.generator_context import (
    GenerationActorError,
    GenerationBlockedError,
    GenerationStaleError,
)


def test_double_layer_mapping_end_to_end_api() -> None:
    with _client() as client:
        project = _post(
            client,
            "/api/projects",
            {"name": "双层口径项目", "bank_name": "示例银行", "description": "验证双层业务口径"},
        )
        table = _post(
            client,
            "/api/target-tables",
            {"project_id": project["id"], "table_code": "YBT_CUSTOMER", "table_name": "客户信息表"},
        )
        target_field = _post(
            client,
            "/api/fields",
            {
                "project_id": project["id"],
                "target_table_id": table["id"],
                "field_code": "CERT_TYPE",
                "field_name": "客户证件类型",
                "field_type": "varchar(20)",
                "required_flag": True,
                "field_definition": "客户身份证件类型",
                "regulatory_description": "按一表通证件类型代码集报送",
            },
        )

        business_system = _post(
            client,
            f"/api/projects/{project['id']}/business-systems",
            {"system_code": "ECIF", "system_name": "客户信息系统", "owner_department": "数据管理部", "enabled": True},
        )
        source_table = _post(
            client,
            f"/api/business-systems/{business_system['id']}/source-tables",
            {"table_code": "ecif_customer", "table_name": "客户基本信息表", "table_comment": "ECIF 客户主表"},
        )
        source_field = _post(
            client,
            f"/api/source-tables/{source_table['id']}/source-fields",
            {"field_code": "cert_type", "field_name": "证件类型", "field_type": "varchar(20)", "field_comment": "客户证件类型"},
        )
        mart_table = _post(
            client,
            f"/api/projects/{project['id']}/mart-tables",
            {
                "table_code": "mart_customer",
                "table_name": "监管客户集市表",
                "subject_area": "客户",
                "table_comment": "监管报送客户主题",
                "is_existing": False,
            },
        )
        mart_field = _post(
            client,
            f"/api/mart-tables/{mart_table['id']}/mart-fields",
            {
                "field_code": "cert_type",
                "field_name": "客户证件类型",
                "field_type": "varchar(20)",
                "field_comment": "统一监管集市证件类型",
                "is_existing": False,
            },
        )

        source_to_mart = _post(
            client,
            f"/api/mart-fields/{mart_field['id']}/source-to-mart-mappings",
            {
                "mapping_name": "ECIF 证件类型入集市",
                "source_system_summary": "ECIF",
                "source_tables_summary": "ecif_customer",
                "source_fields_summary": "cert_type",
                "business_rule": "从 ECIF 客户基本信息取客户证件类型。",
            },
        )
        mart_to_ybt = _post(
            client,
            f"/api/target-fields/{target_field['id']}/mart-to-ybt-mappings",
            {
                "mart_field_id": mart_field["id"],
                "mapping_name": "监管集市证件类型到一表通",
                "mart_table_summary": "mart_customer",
                "mart_field_summary": "cert_type",
                "business_rule": "从监管客户集市表取证件类型并转换为一表通代码。",
            },
        )

        empty_approval = client.post(f"/api/source-to-mart-mappings/{source_to_mart['id']}/approve", json={"reviewed_by": "tester"})
        assert empty_approval.status_code == 400
        assert "final_content" in empty_approval.json()["detail"]

        source_evidence = _post(
            client,
            f"/api/mappings/source_to_mart/{source_to_mart['id']}/evidence",
            {
                "evidence_type": "source_field",
                "evidence_id": source_field["id"],
                "source_name": "ECIF.ecif_customer.cert_type",
                "location_text": "源字段",
                "quoted_content": "客户证件类型字段",
                "evidence_summary": "证明监管集市字段来源于 ECIF 证件类型。",
            },
        )
        ybt_evidence = _post(
            client,
            f"/api/mappings/mart_to_ybt/{mart_to_ybt['id']}/evidence",
            {
                "evidence_type": "target_field",
                "evidence_id": target_field["id"],
                "source_name": "一表通模板",
                "location_text": "YBT_CUSTOMER.CERT_TYPE",
                "quoted_content": "按一表通证件类型代码集报送",
                "evidence_summary": "证明一表通目标字段定义。",
            },
        )

        source_manual = "人工维护的业务系统到监管集市口径"
        ybt_manual = "人工维护的监管集市到一表通口径"
        _put(client, f"/api/source-to-mart-mappings/{source_to_mart['id']}", {"final_content": source_manual})
        _put(client, f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}", {"final_content": ybt_manual})
        source_draft = _post(client, f"/api/source-to-mart-mappings/{source_to_mart['id']}/generate-draft", {})
        ybt_draft = _post(client, f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}/generate-draft", {})

        assert source_draft["final_content"] == source_manual
        assert ybt_draft["final_content"] == ybt_manual
        assert "select " not in source_draft["ai_generated_content"].lower()
        assert "业务系统到监管集市" in source_draft["ai_generated_content"]
        assert "监管集市到一表通" in ybt_draft["ai_generated_content"]
        assert ybt_draft["mart_field_summary"]

        no_evidence_mapping = _post(
            client,
            f"/api/mart-fields/{mart_field['id']}/source-to-mart-mappings",
            {"final_content": "已有人工最终口径，但尚未绑定证据。"},
        )
        no_evidence_approval = client.post(
            f"/api/source-to-mart-mappings/{no_evidence_mapping['id']}/approve",
            json={"reviewed_by": "tester"},
        )
        assert no_evidence_approval.status_code == 400
        assert "evidence" in no_evidence_approval.json()["detail"].lower()

        source_adopted = _post(client, f"/api/source-to-mart-mappings/{source_to_mart['id']}/adopt-ai-draft", {})
        ybt_adopted = _post(client, f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}/adopt-ai-draft", {})
        assert source_adopted["final_content"] == source_adopted["ai_generated_content"]
        assert ybt_adopted["final_content"] == ybt_adopted["ai_generated_content"]

        source_saved = _put(
            client,
            f"/api/source-to-mart-mappings/{source_to_mart['id']}",
            {
                "final_content": "业务系统到监管集市：ECIF 客户证件类型进入 mart_customer.cert_type，空值列入待确认。",
                "open_questions": "请确认 ECIF 证件类型码值是否为最新监管代码集。",
            },
        )
        ybt_saved = _put(
            client,
            f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}",
            {
                "final_content": "监管集市到一表通：mart_customer.cert_type 映射到 CERT_TYPE，并按一表通代码集转换。",
                "open_questions": "请确认报送日期内有效客户口径。",
            },
        )

        source_version = _post(client, f"/api/source-to-mart-mappings/{source_saved['id']}/save-version", {"change_note": "人工确认"})
        ybt_version = _post(client, f"/api/mart-to-ybt-mappings/{ybt_saved['id']}/save-version", {"change_note": "人工确认"})
        source_approved = _post(client, f"/api/source-to-mart-mappings/{source_saved['id']}/approve", {"reviewed_by": "tester"})
        ybt_rejected = _post(client, f"/api/mart-to-ybt-mappings/{ybt_saved['id']}/reject", {"reviewed_by": "tester"})

        assert source_evidence["mapping_type"] == "source_to_mart"
        assert ybt_evidence["mapping_type"] == "mart_to_ybt"
        assert source_version["version_no"] == 1
        assert ybt_version["version_no"] == 1
        assert source_approved["mapping_status"] == "approved"
        assert ybt_rejected["mapping_status"] == "rejected"

        field_export = _get(client, f"/api/target-fields/{target_field['id']}/export/mapping-document?format=markdown")
        table_export = _get(client, f"/api/target-tables/{table['id']}/export/mapping-document?format=markdown")
        project_export = _get(client, f"/api/projects/{project['id']}/export/mapping-document?format=markdown")

        for exported in [field_export, table_export, project_export]:
            markdown = exported["content"]
            assert "一表通字段信息" in markdown
            assert "监管集市字段设计" in markdown
            assert "业务系统到监管集市取数口径" in markdown
            assert "监管集市到一表通取数口径" in markdown
            assert "参考依据" in markdown
            assert "待确认问题" in markdown
            assert "审核状态" in markdown


def test_source_to_mart_route_passes_exact_authorized_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "route") as (db, _, fixture):
        actor = _principal(fixture)
        captured: dict[str, object] = {}

        async def fake_generate(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None = None,
            today_provider=date.today,
        ) -> SourceToMartMapping:
            captured.update(
                session=session,
                mapping_id=mapping_id,
                authorized_project=authorized_project,
                actor=actor,
                as_of=as_of,
                today_provider=today_provider,
            )
            return fixture["mapping"]

        monkeypatch.setattr(mapping_rules, "generate_source_to_mart_draft", fake_generate)
        selected_date = date(2026, 6, 30)
        result = asyncio.run(
            mapping_rules.generate_source_to_mart_mapping_draft(
                fixture["mapping"].id,
                principal=actor,
                as_of=selected_date,
                db=db,
            )
        )

        assert result.id == fixture["mapping"].id
        assert captured["actor"] is actor
        assert captured["authorized_project"] is fixture["project"]
        assert captured["as_of"] == selected_date

        foreign = User(username="foreign-route-user", status="active")
        db.add(foreign)
        db.commit()
        foreign_actor = Principal(foreign.id, foreign.username, foreign.display_name, False)
        with pytest.raises(HTTPException, match="Project not found"):
            asyncio.run(
                mapping_rules.generate_source_to_mart_mapping_draft(
                    fixture["mapping"].id,
                    principal=foreign_actor,
                    as_of=None,
                    db=db,
                )
            )
        assert captured["actor"] is actor

        with pytest.raises(HTTPException) as invalid:
            asyncio.run(
                mapping_rules.generate_source_to_mart_mapping_draft(
                    fixture["mapping"].id,
                    principal=Principal(None, "falsey", None, False),
                    as_of=None,
                    db=db,
                )
            )
        assert invalid.value.status_code in {401, 403}


def test_source_to_mart_service_uses_one_context_and_governed_output_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "context") as (db, _, fixture):
        actor = _principal(fixture)
        calls = {"context": 0, "model": 0}

        def fake_build(*args, **kwargs):
            calls["context"] += 1
            assert kwargs["authorized_project"] is fixture["project"]
            assert kwargs["actor"] is actor
            assert kwargs["explicit_as_of"] == date(2026, 6, 30)
            return _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            )

        async def fake_model(*args, **kwargs):
            calls["model"] += 1
            assert args[2].prompt_key == "source_to_mart_mapping"
            assert args[4].__name__ == "SourceToMartOutput"
            return {
                "source_system_summary": "AI 核心系统",
                "business_rule": "受治理的 AI 业务规则",
                "open_questions": ["模型问题"],
                "confidence_level": "high",
                "final_content_draft": "受治理的业务草稿",
                "mapping_status": "approved",
            }

        monkeypatch.setattr(source_to_mart_generator, "build_generation_context", fake_build)
        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", fake_model)
        original_final = fixture["mapping"].final_content
        original_status = fixture["mapping"].mapping_status

        generated = asyncio.run(
            source_to_mart_generator.generate_source_to_mart_draft(
                db,
                fixture["mapping"].id,
                authorized_project=fixture["project"],
                actor=actor,
                as_of=date(2026, 6, 30),
            )
        )

        assert calls == {"context": 1, "model": 1}
        assert generated.final_content == original_final
        assert generated.mapping_status == original_status
        assert generated.confidence_level == "low"
        assert generated.open_questions.startswith("人工问题保持原样")
        assert "[CTX:MISSING_SOURCE_MAPPING]" in generated.open_questions
        assert "[AI] 模型问题" in generated.open_questions
        assert generated.ai_generated_content == "业务系统到监管集市口径：\n受治理的业务草稿"

        source = inspect.getsource(source_to_mart_generator)
        for forbidden in (
            "HybridRetriever",
            "MappingEvidenceReference",
            "_source_candidates",
            "_evidence_text",
        ):
            assert forbidden not in source


def test_source_to_mart_blocked_readiness_never_calls_model_or_mutates_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "blocked") as (db, _, fixture):
        monkeypatch.setattr(
            source_to_mart_generator,
            "build_generation_context",
            lambda *args, **kwargs: _source_context_envelope(
                can_generate=False,
                snapshot=kwargs["snapshot"],
            ),
        )

        async def forbidden_model(*args, **kwargs):
            raise AssertionError("blocked readiness reached the model")

        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", forbidden_model)
        before = _mapping_state(fixture["mapping"])
        with pytest.raises(GenerationBlockedError, match="CONFLICTING_AUTHORITATIVE_FACTS"):
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        db.expire_all()
        assert _mapping_state(db.get(SourceToMartMapping, fixture["mapping"].id)) == before


def test_source_to_mart_rejects_concurrent_snapshot_change_without_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "stale") as (db, factory, fixture):
        monkeypatch.setattr(
            source_to_mart_generator,
            "build_generation_context",
            lambda *args, **kwargs: _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            ),
        )

        async def mutate_while_model_runs(*args, **kwargs):
            with factory() as concurrent:
                current = concurrent.get(SourceToMartMapping, fixture["mapping"].id)
                current.final_content = "并发人工最终内容"
                concurrent.commit()
            return {
                "business_rule": "不应落库的模型规则",
                "confidence_level": "high",
                "open_questions": ["不应落库的问题"],
            }

        monkeypatch.setattr(
            source_to_mart_generator,
            "execute_runtime_chat",
            mutate_while_model_runs,
        )
        original_draft = fixture["mapping"].ai_generated_content
        with pytest.raises(GenerationStaleError) as stale:
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        assert "task.final_content" in stale.value.changed_fields

        with factory() as verify:
            current = verify.get(SourceToMartMapping, fixture["mapping"].id)
            assert current.final_content == "并发人工最终内容"
            assert current.ai_generated_content == original_draft
            stale_audit = verify.scalar(
                select(AuditLog).where(
                    AuditLog.action == "generate_source_to_mart_stale",
                    AuditLog.resource_id == str(fixture["mapping"].id),
                )
            )
            assert stale_audit is not None
            assert stale_audit.result == "stale"
            assert "task.final_content" in stale_audit.after_summary_json["changed_fields"]
            assert verify.scalar(
                select(AuditLog.id).where(
                    AuditLog.action == "generate_source_to_mart",
                    AuditLog.result == "success",
                )
            ) is None


def test_source_to_mart_revalidates_actor_after_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "actor") as (db, factory, fixture):
        monkeypatch.setattr(
            source_to_mart_generator,
            "build_generation_context",
            lambda *args, **kwargs: _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            ),
        )

        async def disable_actor(*args, **kwargs):
            with factory() as concurrent:
                current = concurrent.get(User, fixture["user"].id)
                current.status = "disabled"
                concurrent.commit()
            return {"business_rule": "不应落库", "confidence_level": "high"}

        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", disable_actor)
        with pytest.raises(GenerationActorError, match="active User"):
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        with factory() as verify:
            current = verify.get(SourceToMartMapping, fixture["mapping"].id)
            assert current.ai_generated_content == "旧 AI 草稿"


def test_mart_to_ybt_route_passes_exact_authorized_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "mart-route") as (db, _, fixture):
        mart_mapping = _seed_mart_to_ybt_mapping(db, fixture, "mart-route")
        actor = _principal(fixture)
        captured: dict[str, object] = {}

        async def fake_generate(
            session: Session,
            mapping_id: int,
            *,
            authorized_project: Project,
            actor: Principal,
            as_of: date | None = None,
            today_provider=date.today,
        ) -> MartToYbtMapping:
            captured.update(
                session=session,
                mapping_id=mapping_id,
                authorized_project=authorized_project,
                actor=actor,
                as_of=as_of,
                today_provider=today_provider,
            )
            return mart_mapping

        monkeypatch.setattr(mapping_rules, "generate_mart_to_ybt_draft", fake_generate)
        selected_date = date(2026, 6, 30)
        result = asyncio.run(
            mapping_rules.generate_mart_to_ybt_mapping_draft(
                mart_mapping.id,
                principal=actor,
                as_of=selected_date,
                db=db,
            )
        )

        assert result.id == mart_mapping.id
        assert captured["actor"] is actor
        assert captured["authorized_project"] is fixture["project"]
        assert captured["as_of"] == selected_date


def test_mart_to_ybt_service_uses_frozen_context_upstream_and_output_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "mart-context") as (db, factory, fixture):
        mart_mapping = _seed_mart_to_ybt_mapping(db, fixture, "mart-context")
        actor = _principal(fixture)
        calls = {"context": 0, "model": 0}

        def fake_build(*args, **kwargs):
            calls["context"] += 1
            assert kwargs["authorized_project"] is fixture["project"]
            assert kwargs["actor"] is actor
            return _mart_context_envelope(snapshot=kwargs["snapshot"])

        async def fake_model(*args, **kwargs):
            calls["model"] += 1
            assert args[2].prompt_key == "mart_to_ybt_mapping"
            assert args[4].__name__ == "MartToYbtOutput"
            assert "APPROVED_CONTEXT_RULE" in args[3]
            with factory() as concurrent:
                upstream = concurrent.get(
                    SourceToMartMapping,
                    fixture["mapping"].id,
                )
                upstream.final_content = "模型执行期间更新的上游规则"
                concurrent.commit()
            return {
                "mart_table_summary": "AI 集市表",
                "business_rule": "受治理的 Mart-to-YBT 规则",
                "open_questions": ["Mart 模型问题"],
                "confidence_level": "high",
                "final_content_draft": "受治理的报送草稿",
                "mapping_status": "approved",
            }

        monkeypatch.setattr(mart_to_ybt_generator, "build_generation_context", fake_build)
        monkeypatch.setattr(mart_to_ybt_generator, "execute_runtime_chat", fake_model)
        original_final = mart_mapping.final_content
        original_status = mart_mapping.mapping_status

        generated = asyncio.run(
            mart_to_ybt_generator.generate_mart_to_ybt_draft(
                db,
                mart_mapping.id,
                authorized_project=fixture["project"],
                actor=actor,
                as_of=date(2026, 6, 30),
            )
        )

        assert calls == {"context": 1, "model": 1}
        assert generated.final_content == original_final
        assert generated.mapping_status == original_status
        assert generated.confidence_level == "low"
        assert generated.open_questions.startswith("人工 Mart 问题")
        assert "[CTX:MISSING_MART_TO_YBT_MAPPING]" in generated.open_questions
        assert "[AI] Mart 模型问题" in generated.open_questions
        assert generated.ai_generated_content == "监管集市到一表通口径：\n受治理的报送草稿"

        source = inspect.getsource(mart_to_ybt_generator)
        for forbidden in (
            "HybridRetriever",
            "MappingEvidenceReference",
            "SourceToMartMapping",
            "_source_to_mart_summary",
            "_evidence_text",
        ):
            assert forbidden not in source


def test_mart_to_ybt_blocked_readiness_never_calls_model_or_mutates_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "mart-blocked") as (db, _, fixture):
        mart_mapping = _seed_mart_to_ybt_mapping(db, fixture, "mart-blocked")
        monkeypatch.setattr(
            mart_to_ybt_generator,
            "build_generation_context",
            lambda *args, **kwargs: _mart_context_envelope(
                snapshot=kwargs["snapshot"],
                can_generate=False,
            ),
        )

        async def forbidden_model(*args, **kwargs):
            raise AssertionError("blocked readiness reached the model")

        monkeypatch.setattr(mart_to_ybt_generator, "execute_runtime_chat", forbidden_model)
        before = _mart_mapping_state(mart_mapping)
        with pytest.raises(GenerationBlockedError, match="CONFLICTING_AUTHORITATIVE_FACTS"):
            asyncio.run(
                mart_to_ybt_generator.generate_mart_to_ybt_draft(
                    db,
                    mart_mapping.id,
                    authorized_project=fixture["project"],
                    actor=_principal(fixture),
                )
            )
        db.expire_all()
        assert _mart_mapping_state(db.get(MartToYbtMapping, mart_mapping.id)) == before


def test_generation_routes_bound_context_failures_without_exposing_raw_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "bounded-error") as (db, _, fixture):
        mart_mapping = _seed_mart_to_ybt_mapping(db, fixture, "bounded-error")
        actor = _principal(fixture)
        raw_secret = "RAW_REGULATORY_CONTEXT_SHOULD_NOT_ESCAPE"

        async def fail_context(*args, **kwargs):
            raise ValueError(raw_secret)

        for route, service_name, mapping_id in (
            (
                mapping_rules.generate_source_to_mart_mapping_draft,
                "generate_source_to_mart_draft",
                fixture["mapping"].id,
            ),
            (
                mapping_rules.generate_mart_to_ybt_mapping_draft,
                "generate_mart_to_ybt_draft",
                mart_mapping.id,
            ),
        ):
            monkeypatch.setattr(mapping_rules, service_name, fail_context)
            with pytest.raises(HTTPException) as denied:
                asyncio.run(
                    route(
                        mapping_id,
                        principal=actor,
                        as_of=date(2026, 6, 30),
                        db=db,
                    )
                )
            assert denied.value.status_code == 409
            assert denied.value.detail == {"code": "generation-context-failed"}
            assert raw_secret not in str(denied.value.detail)
            db.rollback()


def test_source_to_mart_rejects_every_local_snapshot_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "snapshot-categories") as (db, factory, fixture):
        monkeypatch.setattr(
            source_to_mart_generator,
            "build_generation_context",
            lambda *args, **kwargs: _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            ),
        )
        actor = _principal(fixture)
        mutations = (
            (SourceToMartMapping, fixture["mapping"].id, "business_rule", "并发规则", "task.business_rule"),
            (SourceToMartMapping, fixture["mapping"].id, "open_questions", "并发人工问题", "task.open_questions"),
            (SourceToMartMapping, fixture["mapping"].id, "mapping_status", "reviewed", "task.mapping_status"),
            (Project, fixture["project"].id, "confidentiality_level", "confidential", "project.confidentiality_level"),
            (Project, fixture["project"].id, "project_status", "suspended", "project.project_status"),
            (Project, fixture["project"].id, "governance_workflow_enabled", False, "project.governance_workflow_enabled"),
        )

        for model, row_id, attribute, value, expected_field in mutations:
            async def mutate_local_snapshot(*args, **kwargs):
                with factory() as concurrent:
                    current = concurrent.get(model, row_id)
                    setattr(current, attribute, value)
                    concurrent.commit()
                return {
                    "business_rule": "不得落库的模型规则",
                    "confidence_level": "high",
                }

            monkeypatch.setattr(
                source_to_mart_generator,
                "execute_runtime_chat",
                mutate_local_snapshot,
            )
            db.expire_all()
            old_draft = db.get(
                SourceToMartMapping,
                fixture["mapping"].id,
            ).ai_generated_content
            with pytest.raises(GenerationStaleError) as stale:
                asyncio.run(
                    source_to_mart_generator.generate_source_to_mart_draft(
                        db,
                        fixture["mapping"].id,
                        authorized_project=fixture["project"],
                        actor=actor,
                    )
                )
            assert expected_field in stale.value.changed_fields
            with factory() as verify:
                assert getattr(verify.get(model, row_id), attribute) == value
                current = verify.get(SourceToMartMapping, fixture["mapping"].id)
                assert current.ai_generated_content == old_draft

        with factory() as verify:
            success_count = len(
                verify.scalars(
                    select(AuditLog.id).where(
                        AuditLog.action == "generate_source_to_mart",
                        AuditLog.result == "success",
                    )
                ).all()
            )
            stale_count = len(
                verify.scalars(
                    select(AuditLog.id).where(
                        AuditLog.action == "generate_source_to_mart_stale",
                        AuditLog.result == "stale",
                    )
                ).all()
            )
            assert success_count == 0
            assert stale_count == len(mutations)


def test_source_to_mart_rechecks_permission_after_model_without_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "permission") as (db, factory, fixture):
        monkeypatch.setattr(
            source_to_mart_generator,
            "build_generation_context",
            lambda *args, **kwargs: _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            ),
        )
        permission_calls: list[Principal] = []

        def permission_spy(session: Session, actor: Principal) -> PermissionService:
            permission_calls.append(actor)
            return PermissionService(session, actor)

        monkeypatch.setattr(source_to_mart_generator, "PermissionService", permission_spy)

        async def demote_actor(*args, **kwargs):
            with factory() as concurrent:
                membership = concurrent.get(
                    ProjectMembership,
                    fixture["membership"].id,
                )
                membership.project_role = "viewer"
                concurrent.commit()
            return {"business_rule": "不得落库", "confidence_level": "high"}

        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", demote_actor)
        actor = _principal(fixture)
        with pytest.raises(HTTPException) as denied:
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=actor,
                )
            )
        assert denied.value.status_code == 403
        assert permission_calls == [actor]
        with factory() as verify:
            current = verify.get(SourceToMartMapping, fixture["mapping"].id)
            assert current.ai_generated_content == "旧 AI 草稿"
            assert verify.scalar(
                select(AuditLog.id).where(
                    AuditLog.action == "generate_source_to_mart",
                    AuditLog.result == "success",
                )
            ) is None


def test_double_layer_generation_failures_never_fallback_or_partially_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "fail-closed") as (db, _, fixture):
        actor = _principal(fixture)
        before = _mapping_state(fixture["mapping"])
        model_calls = 0

        def builder_failure(*args, **kwargs):
            raise RuntimeError("Context unavailable")

        async def forbidden_model(*args, **kwargs):
            nonlocal model_calls
            model_calls += 1
            return {"business_rule": "fallback"}

        monkeypatch.setattr(source_to_mart_generator, "build_generation_context", builder_failure)
        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", forbidden_model)
        with pytest.raises(RuntimeError, match="Context unavailable"):
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=actor,
                )
            )
        assert model_calls == 0
        db.rollback()
        db.expire_all()
        assert _mapping_state(db.get(SourceToMartMapping, fixture["mapping"].id)) == before

        monkeypatch.setattr(
            source_to_mart_generator,
            "build_generation_context",
            lambda *args, **kwargs: _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            ),
        )

        async def interrupted_model(*args, **kwargs):
            raise RuntimeError("model interrupted")

        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", interrupted_model)
        with pytest.raises(RuntimeError, match="model interrupted"):
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=actor,
                )
            )
        db.rollback()
        db.expire_all()
        assert _mapping_state(db.get(SourceToMartMapping, fixture["mapping"].id)) == before


def test_generation_audit_is_redacted_and_query_delta_is_row_count_invariant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _source_service_session(tmp_path, "audit-query") as (db, _, fixture):
        actor = _principal(fixture)
        raw_prompt = "RAW_CONTEXT_PROMPT_CONTENT"
        raw_output = "RAW_MODEL_DRAFT_CONTENT"

        def fake_build(*args, **kwargs):
            envelope = _source_context_envelope(
                can_generate=True,
                snapshot=kwargs["snapshot"],
            )
            envelope.projection.prompt_text = raw_prompt
            return envelope

        async def fake_model(*args, **kwargs):
            return {
                "business_rule": raw_output,
                "final_content_draft": raw_output,
                "confidence_level": "high",
            }

        monkeypatch.setattr(source_to_mart_generator, "build_generation_context", fake_build)
        monkeypatch.setattr(source_to_mart_generator, "execute_runtime_chat", fake_model)
        engine = db.get_bind()
        statement_count = 0

        def count_statement(*args, **kwargs):
            nonlocal statement_count
            statement_count += 1

        def measured_generation() -> int:
            nonlocal statement_count
            db.expire_all()
            statement_count = 0
            asyncio.run(
                source_to_mart_generator.generate_source_to_mart_draft(
                    db,
                    fixture["mapping"].id,
                    authorized_project=fixture["project"],
                    actor=actor,
                )
            )
            return statement_count

        event.listen(engine, "before_cursor_execute", count_statement)
        try:
            baseline_count = measured_generation()
            db.add_all(
                SourceToMartMapping(
                    project_id=fixture["project"].id,
                    mart_field_id=fixture["mart_field"].id,
                    mapping_name=f"unrelated-{index}",
                    mapping_status="draft",
                    business_rule=f"unrelated-rule-{index}",
                    confidence_level="low",
                    lineage_status="not_linked",
                )
                for index in range(40)
            )
            db.commit()
            growth_count = measured_generation()
        finally:
            event.remove(engine, "before_cursor_execute", count_statement)

        assert baseline_count > 0
        assert growth_count == baseline_count
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "generate_source_to_mart",
                AuditLog.result == "success",
            )
        ).all()
        assert len(audits) == 2
        serialized = str(
            [
                (audit.before_summary_json, audit.after_summary_json)
                for audit in audits
            ]
        )
        assert raw_prompt not in serialized
        assert raw_output not in serialized
        assert "prompt_projection_hash" in serialized
        assert "output_field_names" in serialized


def test_double_layer_write_order_and_no_fallback_are_static_contracts() -> None:
    specifications = (
        (source_to_mart_generator, "select(SourceToMartMapping)"),
        (mart_to_ybt_generator, "select(MartToYbtMapping)"),
    )
    for module, task_lock in specifications:
        source = inspect.getsource(module)
        transaction = source.index("with db.begin():")
        actor_check = source.index("validate_generation_actor(db, actor)", transaction)
        permission = source.index("PermissionService(db, actor)", actor_check)
        project_lock = source.index("select(Project)", permission)
        mapping_lock = source.index(task_lock, project_lock)
        assert transaction < actor_check < permission < project_lock < mapping_lock
        assert source.count("build_generation_context(") == 1
        for forbidden in (
            "HybridRetriever",
            "MappingEvidenceReference",
            "_source_candidates",
            "_source_to_mart_summary",
            "_evidence_text",
        ):
            assert forbidden not in source


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


@contextmanager
def _source_service_session(
    tmp_path: Path,
    suffix: str,
) -> Iterator[tuple[Session, sessionmaker, dict[str, object]]]:
    database_path = tmp_path / f"source-to-mart-{suffix}.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    fixture = _seed_source_mapping(db, suffix)
    try:
        yield db, factory, fixture
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_source_mapping(db: Session, suffix: str) -> dict[str, object]:
    user = User(
        username=f"source-generator-{suffix}",
        display_name=f"Source Generator {suffix}",
        status="active",
    )
    project = Project(
        name=f"Source generator {suffix}",
        project_status="active",
        confidentiality_level="internal",
        governance_workflow_enabled=True,
    )
    db.add_all([user, project])
    db.flush()
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        project_role="technical_analyst",
        status="active",
    )
    mart_table = MartTable(
        project_id=project.id,
        table_code=f"MART_{suffix.upper()}",
        table_name="监管集市",
    )
    db.add_all([membership, mart_table])
    db.flush()
    mart_field = MartField(
        project_id=project.id,
        mart_table_id=mart_table.id,
        field_code=f"FIELD_{suffix.upper()}",
        field_name="监管字段",
        field_type="varchar(64)",
    )
    db.add(mart_field)
    db.flush()
    mapping = SourceToMartMapping(
        project_id=project.id,
        mart_field_id=mart_field.id,
        mapping_name=f"Source-to-Mart {suffix}",
        mapping_status="draft",
        source_system_summary="人工核心系统",
        business_rule="人工原规则",
        open_questions="人工问题保持原样",
        ai_generated_content="旧 AI 草稿",
        final_content="人工最终内容",
        confidence_level="medium",
        lineage_status="not_linked",
    )
    db.add(mapping)
    db.commit()
    for row in (user, project, membership, mart_table, mart_field, mapping):
        db.refresh(row)
    return {
        "user": user,
        "project": project,
        "membership": membership,
        "mart_table": mart_table,
        "mart_field": mart_field,
        "mapping": mapping,
    }


def _seed_mart_to_ybt_mapping(
    db: Session,
    fixture: dict[str, object],
    suffix: str,
) -> MartToYbtMapping:
    project = fixture["project"]
    mart_field = fixture["mart_field"]
    target_table = TargetTable(
        project_id=project.id,
        table_code=f"YBT_{suffix.upper()}",
        table_name="一表通目标表",
        description="监管目标表",
    )
    db.add(target_table)
    db.flush()
    target_field = TargetField(
        project_id=project.id,
        target_table_id=target_table.id,
        field_code=f"TARGET_{suffix.upper()}",
        field_name="一表通目标字段",
        field_type="varchar(64)",
        required_flag=True,
        field_definition="监管目标定义",
    )
    db.add(target_field)
    db.flush()
    mapping = MartToYbtMapping(
        project_id=project.id,
        target_field_id=target_field.id,
        mart_field_id=mart_field.id,
        mapping_name=f"Mart-to-YBT {suffix}",
        mapping_status="draft",
        mart_table_summary="人工集市表",
        mart_field_summary="人工集市字段",
        business_rule="人工报送规则",
        open_questions="人工 Mart 问题",
        ai_generated_content="旧 Mart AI 草稿",
        final_content="人工 Mart 最终内容",
        confidence_level="medium",
        lineage_status="not_linked",
    )
    db.add(mapping)
    fixture["mapping"].mapping_status = "approved"
    fixture["mapping"].final_content = "APPROVED_CONTEXT_RULE"
    db.commit()
    db.refresh(mapping)
    db.refresh(fixture["mapping"])
    return mapping


def _principal(fixture: dict[str, object]) -> Principal:
    user = fixture["user"]
    return Principal(user.id, user.username, user.display_name, False)


def _source_context_envelope(
    *,
    can_generate: bool,
    snapshot: object,
) -> SimpleNamespace:
    blocking = [] if can_generate else ["CONFLICTING_AUTHORITATIVE_FACTS"]
    context_questions = [
        SimpleNamespace(
            question_code="MISSING_SOURCE_MAPPING",
            question_text="请确认来源映射。",
            priority="high",
            target_type="source_to_mart",
            target_id=1,
            resolution_state="open",
        )
    ]
    projection = SimpleNamespace(
        task_type="source_to_mart",
        prompt_text="受治理的 Source-to-Mart Context 投影",
        confidentiality_levels=["internal"],
        context_questions=context_questions,
        readiness=SimpleNamespace(
            can_generate=can_generate,
            blocking_reasons=blocking,
            warnings=["MISSING_SOURCE_MAPPING"],
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
        "context_question_codes": ["MISSING_SOURCE_MAPPING"],
        "retrieval_log_ids": [101],
        "readiness_can_generate": can_generate,
        "readiness_confidence_cap": "low",
        "prompt_projection_hash": "a" * 64,
        "prompt_projection_truncated": False,
    }
    return SimpleNamespace(
        snapshot=snapshot,
        projection=projection,
        trace=SimpleNamespace(
            retrieval_log_ids=[101],
            model_dump=lambda **kwargs: dict(trace_values),
        ),
    )


def _mart_context_envelope(
    *,
    snapshot: object,
    can_generate: bool = True,
) -> SimpleNamespace:
    blocking = [] if can_generate else ["CONFLICTING_AUTHORITATIVE_FACTS"]
    context_questions = [
        SimpleNamespace(
            question_code="MISSING_MART_TO_YBT_MAPPING",
            question_text="请确认 Mart-to-YBT 映射。",
            priority="high",
            target_type="mart_to_ybt",
            target_id=1,
            resolution_state="open",
        )
    ]
    projection = SimpleNamespace(
        task_type="mart_to_ybt",
        prompt_text=(
            "受治理的 Mart-to-YBT Context 投影\n"
            "已批准 Source-to-Mart：APPROVED_CONTEXT_RULE"
        ),
        confidentiality_levels=["internal"],
        context_questions=context_questions,
        readiness=SimpleNamespace(
            can_generate=can_generate,
            blocking_reasons=blocking,
            warnings=["MISSING_MART_TO_YBT_MAPPING"],
            confidence_cap="low",
        ),
        upstream_rule_summaries=["APPROVED_CONTEXT_RULE"],
    )
    trace_values = {
        "context_schema_version": "1.0",
        "context_built_at": "2026-06-30T00:00:00+00:00",
        "resolved_as_of": "2026-06-30",
        "as_of_source": "explicit",
        "context_fact_count": 1,
        "context_conflict_codes": blocking,
        "context_question_codes": ["MISSING_MART_TO_YBT_MAPPING"],
        "retrieval_log_ids": [202],
        "readiness_can_generate": can_generate,
        "readiness_confidence_cap": "low",
        "prompt_projection_hash": "b" * 64,
        "prompt_projection_truncated": False,
    }
    return SimpleNamespace(
        snapshot=snapshot,
        projection=projection,
        trace=SimpleNamespace(
            retrieval_log_ids=[202],
            model_dump=lambda **kwargs: dict(trace_values),
        ),
    )


def _mapping_state(mapping: SourceToMartMapping) -> tuple[object, ...]:
    return (
        mapping.source_system_summary,
        mapping.business_rule,
        mapping.open_questions,
        mapping.ai_generated_content,
        mapping.final_content,
        mapping.confidence_level,
        mapping.mapping_status,
    )


def _mart_mapping_state(mapping: MartToYbtMapping) -> tuple[object, ...]:
    return (
        mapping.mart_table_summary,
        mapping.business_rule,
        mapping.open_questions,
        mapping.ai_generated_content,
        mapping.final_content,
        mapping.confidence_level,
        mapping.mapping_status,
    )


def _post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def _put(client: TestClient, path: str, payload: dict) -> dict:
    response = client.put(path, json=payload)
    response.raise_for_status()
    return response.json()


def _get(client: TestClient, path: str) -> dict:
    response = client.get(path)
    response.raise_for_status()
    return response.json()
