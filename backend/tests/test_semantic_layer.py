from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    Institution,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    MartField,
    MartTable,
    Project,
    ProjectMembership,
    ProductScenario,
    ReviewTask,
    SemanticBinding,
    SemanticConcept,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    MartToYbtMapping,
    BusinessSystem,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.governance.workflow import decide_task, start_workflow
from app.services.semantic.entity_adapter import SemanticEntityAdapter
from app.services.semantic.status_policy import (
    SemanticVisibilityMode,
    audit_only_statuses,
    candidate_statuses,
    is_visible,
    trusted_statuses,
)


def test_semantic_concept_crud_duplicate_and_project_institution_isolation() -> None:
    with _semantic_client() as (client, sessions):
        project_a, project_b = _projects(sessions)
        created = _post(client, f"/api/projects/{project_a}/semantic-concepts", {
            "concept_type": "business_term",
            "concept_code": " cust_no ",
            "concept_name": "客户统一编号",
            "aliases_json": ["统一客户号", "统一客户号", "  "],
            "status": "ai_suggested",
            "source_type": "ai",
        })
        assert created["concept_code"] == "CUST_NO"
        assert created["institution_id"] is not None
        assert created["aliases_json"] == ["统一客户号"]

        duplicate = client.post(f"/api/projects/{project_a}/semantic-concepts", json={
            "concept_type": "business_term", "concept_code": "CUST_NO", "concept_name": "重复",
        })
        assert duplicate.status_code == 409

        hidden = client.get(f"/api/projects/{project_b}/semantic-concepts/{created['id']}")
        assert hidden.status_code == 404
        assert client.get(f"/api/projects/{project_b}/semantic-concepts").json() == []

        updated = client.patch(
            f"/api/projects/{project_a}/semantic-concepts/{created['id']}",
            json={"definition": "全行客户唯一标识", "confidence_level": "high"},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2


def test_bindings_validate_targets_and_connect_required_entity_families() -> None:
    with _semantic_client() as (client, sessions):
        project_a, project_b = _projects(sessions)
        entities = _required_binding_entities(sessions, project_a)
        foreign_field = _target_field(sessions, project_b, "OTHER")
        concept = _post(client, f"/api/projects/{project_a}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "CUST_NO", "concept_name": "客户统一编号",
        })

        for entity_type, entity_id in entities.items():
            response = client.post(f"/api/projects/{project_a}/semantic-bindings", json={
                "semantic_concept_id": concept["id"],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "binding_type": "represents",
                "status": "draft",
            })
            assert response.status_code == 201, response.text

        duplicate = client.post(f"/api/projects/{project_a}/semantic-bindings", json={
            "semantic_concept_id": concept["id"], "entity_type": "target_field",
            "entity_id": entities["target_field"], "binding_type": "represents",
        })
        assert duplicate.status_code == 409

        cross_project = client.post(f"/api/projects/{project_a}/semantic-bindings", json={
            "semantic_concept_id": concept["id"], "entity_type": "target_field",
            "entity_id": foreign_field, "binding_type": "represents",
        })
        assert cross_project.status_code == 400

        listed = client.get(
            f"/api/projects/{project_a}/semantic-bindings",
            params={"semantic_concept_id": concept["id"]},
        ).json()
        assert {item["entity_type"] for item in listed} == set(entities)


def test_relations_graph_path_cycles_and_depth_bound() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        customer = _concept(client, project_id, "CUSTOMER", "客户")
        interbank = _concept(client, project_id, "INTERBANK_CUSTOMER", "同业客户")
        identifier = _concept(client, project_id, "CUST_NO", "客户统一编号")
        customer_type = _concept(client, project_id, "CUST_TYPE", "客户类型")

        relations = [
            (interbank, "is_a", customer),
            (interbank, "identified_by", identifier),
            (interbank, "classified_by", customer_type),
            (customer_type, "related_to", interbank),
        ]
        created = []
        for source, relation_type, target in relations:
            created.append(_post(client, f"/api/projects/{project_id}/semantic-relations", {
                "source_concept_id": source,
                "relation_type": relation_type,
                "target_concept_id": target,
            }))

        self_edge = client.post(f"/api/projects/{project_id}/semantic-relations", json={
            "source_concept_id": customer, "relation_type": "related_to", "target_concept_id": customer,
        })
        assert self_edge.status_code == 400

        duplicate = client.post(f"/api/projects/{project_id}/semantic-relations", json={
            "source_concept_id": interbank, "relation_type": "is_a", "target_concept_id": customer,
        })
        assert duplicate.status_code == 409

        neighbors = client.get(
            f"/api/projects/{project_id}/semantic-concepts/{interbank}/neighbors",
            params={"max_depth": 5},
        )
        assert neighbors.status_code == 200
        assert {node["concept"]["id"] for node in neighbors.json()["nodes"]} == {
            customer, interbank, identifier, customer_type,
        }

        path = client.get(f"/api/projects/{project_id}/semantic-path", params={
            "source_concept_id": customer_type, "target_concept_id": customer, "max_depth": 5,
        }).json()
        assert path["found"] is True
        assert path["concept_ids"] == [customer_type, interbank, customer]

        too_deep = client.get(
            f"/api/projects/{project_id}/semantic-concepts/{customer}/neighbors",
            params={"max_depth": 6},
        )
        assert too_deep.status_code == 422


def test_status_transition_is_human_explicit_and_audited() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        concept = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "regulatory_rule", "concept_code": "RULE_1", "concept_name": "同业客户纳入规则",
            "status": "ai_suggested", "source_type": "ai",
        })
        assert concept["confirmed_at"] is None

        confirmed = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "confirmed", "comment": "人工复核通过"},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
        assert confirmed.json()["confirmed_by"] == "legacy-system"
        assert confirmed.json()["confirmed_at"] is not None

        locked_edit = client.patch(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}",
            json={"definition": "不应覆盖已确认事实"},
        )
        assert locked_edit.status_code == 409

        invalid = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "draft"},
        )
        assert invalid.status_code == 409

        with sessions() as db:
            audit = db.scalar(select(AuditLog).where(
                AuditLog.resource_type == "semantic_concept",
                AuditLog.resource_id == str(concept["id"]),
                AuditLog.action == "semantic_status_transition",
            ))
            assert audit is not None
            assert audit.before_summary_json["status"] == "ai_suggested"
            assert audit.after_summary_json["status"] == "confirmed"


def test_semantic_governance_review_confirms_target_through_existing_review_tasks() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        concept = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "regulatory_rule", "concept_code": "REVIEW_RULE",
            "concept_name": "待审核监管规则", "status": "ai_suggested", "source_type": "ai",
        })
        with sessions() as db:
            project = db.get(Project, project_id)
            project.governance_workflow_enabled = True
            reviewer = User(username="semantic_business_reviewer")
            final_reviewer = User(username="semantic_final_reviewer")
            db.add_all([reviewer, final_reviewer])
            db.flush()
            db.add_all([
                ProjectMembership(project_id=project_id, user_id=reviewer.id, project_role="business_reviewer"),
                ProjectMembership(project_id=project_id, user_id=final_reviewer.id, project_role="final_reviewer"),
            ])
            db.commit()

            instance = start_workflow(
                db,
                project_id=project_id,
                workflow_key="semantic_governance_review",
                target_type="semantic_concept",
                target_id=concept["id"],
                created_by=reviewer.id,
                assignments={"business_reviewer": reviewer.id, "final_reviewer": final_reviewer.id},
            )
            first = db.scalar(select(ReviewTask).where(
                ReviewTask.workflow_instance_id == instance.id,
                ReviewTask.step_key == "business_review",
            ))
            decide_task(db, first, Principal(reviewer.id, reviewer.username, None), "approved", "业务口径通过")
            final = db.scalar(select(ReviewTask).where(
                ReviewTask.workflow_instance_id == instance.id,
                ReviewTask.step_key == "final_review",
            ))
            decide_task(db, final, Principal(final_reviewer.id, final_reviewer.username, None), "approved", "最终通过")
            db.refresh(project)
            semantic = db.get(SemanticConcept, concept["id"])
            assert semantic.status == "confirmed"
            assert semantic.confirmed_by == final_reviewer.username

        direct_confirmation = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "confirmed"},
        )
        assert direct_confirmation.status_code == 409


def test_deterministic_resolver_prioritizes_code_name_alias_and_comment() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        field_id = _target_field(sessions, project_id, "CUST_NO", name="客户编号", comment="全行客户统一编号")
        exact_code = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "CUST_NO", "concept_name": "客户标识",
        })
        _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "OTHER", "concept_name": "客户编号",
        })
        _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "ALIAS", "concept_name": "客户号",
            "aliases_json": ["客户编号"],
        })

        first = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id,
        })
        second = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id,
        })
        assert first == second
        assert first["candidates"][0]["semantic_concept_id"] == exact_code["id"]
        assert first["candidates"][0]["match_reason"] == "exact_code"
        assert [item["score"] for item in first["candidates"]] == sorted(
            [item["score"] for item in first["candidates"]], reverse=True
        )


def test_resolver_confirmed_binding_precedes_text_and_is_bounded() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        field_id = _target_field(sessions, project_id, "CUST_NO", name="客户编号", comment="统一客户编号")
        binding_concept = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "BOUND", "concept_name": "绑定概念",
        })
        exact_code = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "CUST_NO", "concept_name": "客户编号",
        })
        binding = _post(client, f"/api/projects/{project_id}/semantic-bindings", {
            "semantic_concept_id": binding_concept["id"], "entity_type": "target_field",
            "entity_id": field_id, "status": "draft",
        })
        with sessions() as db:
            db.get(SemanticConcept, binding_concept["id"]).status = "confirmed"
            db.get(SemanticConcept, exact_code["id"]).status = "confirmed"
            db.get(SemanticBinding, binding["id"]).status = "confirmed"
            db.commit()

        first = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id,
        })
        second = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id,
        })
        assert first == second
        assert first["candidates"][0]["semantic_concept_id"] == binding_concept["id"]
        assert first["candidates"][0]["match_reason"] == "confirmed_binding"
        assert first["candidates"][0]["status"] == "ai_suggested"
        assert len(first["candidates"][0]["evidence"]) <= 3
        assert first["candidates"][0]["provenance"]["project_id"] == project_id


def test_semantic_entity_adapter_describes_all_allow_listed_types() -> None:
    with _semantic_client() as (_, sessions):
        project_id, _ = _projects(sessions)
        entities = _required_binding_entities(sessions, project_id)
        with sessions() as db:
            descriptors = [
                SemanticEntityAdapter.describe(db, project_id, entity_type, entity_id)
                for entity_type, entity_id in entities.items()
            ]
        assert set(entities) == {
            "target_table", "target_field", "mart_table", "mart_field", "source_table", "source_field",
            "scenario", "knowledge_unit", "source_to_mart_mapping", "mart_to_ybt_mapping",
            "scenario_business_mapping", "scenario_technical_lineage",
        }
        assert all(item.project_id == project_id for item in descriptors)
        assert all(item.semantic_text and len(item.semantic_text) <= 4000 for item in descriptors)
        assert all(len(item.source_refs) <= 8 for item in descriptors)
        assert all("__dict__" not in item.semantic_text for item in descriptors)


def test_visibility_policy_and_candidate_mode_never_admit_audit_statuses() -> None:
    assert trusted_statuses() == ("confirmed",)
    assert candidate_statuses() == ("confirmed", "draft", "ai_suggested")
    assert audit_only_statuses() == ("rejected", "deprecated")
    assert is_visible("confirmed", SemanticVisibilityMode.TRUSTED)
    assert is_visible("draft", SemanticVisibilityMode.CANDIDATE)
    assert not is_visible("rejected", SemanticVisibilityMode.CANDIDATE)

    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        field_id = _target_field(sessions, project_id, "MATCH", name="匹配字段", comment="监管匹配")
        concepts = {}
        for status in ("draft", "ai_suggested", "rejected", "deprecated"):
            concepts[status] = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
                "concept_type": "business_term", "concept_code": f"{status.upper()}_MATCH",
                "concept_name": "匹配字段", "status": status if status in {"draft", "ai_suggested"} else "draft",
            })
        with sessions() as db:
            db.get(SemanticConcept, concepts["rejected"]["id"]).status = "rejected"
            db.get(SemanticConcept, concepts["deprecated"]["id"]).status = "deprecated"
            db.commit()

        trusted = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id,
        })
        candidate = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id, "mode": "candidate",
        })
        trusted_ids = {item["semantic_concept_id"] for item in trusted["candidates"]}
        candidate_ids = {item["semantic_concept_id"] for item in candidate["candidates"]}
        assert concepts["rejected"]["id"] not in trusted_ids | candidate_ids
        assert concepts["deprecated"]["id"] not in trusted_ids | candidate_ids
        assert concepts["draft"]["id"] not in trusted_ids
        assert concepts["draft"]["id"] in candidate_ids
        assert concepts["ai_suggested"]["id"] in candidate_ids
        assert all(item["status"] == "ai_suggested" for item in candidate["candidates"])


def _concept(client: TestClient, project_id: int, code: str, name: str) -> int:
    return _post(client, f"/api/projects/{project_id}/semantic-concepts", {
        "concept_type": "business_term", "concept_code": code, "concept_name": name,
    })["id"]


def _projects(sessions: sessionmaker) -> tuple[int, int]:
    with sessions() as db:
        institution_a = Institution(institution_code="BANK_A", institution_name="示例银行 A")
        institution_b = Institution(institution_code="BANK_B", institution_name="示例银行 B")
        db.add_all([institution_a, institution_b])
        db.flush()
        project_a = Project(name="语义项目 A", institution_id=institution_a.id)
        project_b = Project(name="语义项目 B", institution_id=institution_b.id)
        db.add_all([project_a, project_b])
        db.commit()
        return project_a.id, project_b.id


def _target_field(sessions: sessionmaker, project_id: int, code: str, *, name: str = "字段", comment: str | None = None) -> int:
    with sessions() as db:
        table = TargetTable(project_id=project_id, table_code=f"T_{code}", table_name=f"表 {code}")
        db.add(table)
        db.flush()
        field = TargetField(
            project_id=project_id, target_table_id=table.id, field_code=code,
            field_name=name, regulatory_description=comment,
        )
        db.add(field)
        db.commit()
        return field.id


def _required_binding_entities(sessions: sessionmaker, project_id: int) -> dict[str, int]:
    with sessions() as db:
        target_table = TargetTable(project_id=project_id, table_code="YBT_CUST", table_name="客户表")
        mart_table = MartTable(project_id=project_id, table_code="MART_CUST", table_name="客户集市")
        system = BusinessSystem(project_id=project_id, system_code="ECIF", system_name="客户系统")
        scenario = ProductScenario(
            project_id=project_id, scenario_code="CUSTOMER", scenario_name="客户场景",
            description="客户监管报送场景", business_owner="业务团队", tech_owner="技术团队",
        )
        db.add_all([target_table, mart_table, system, scenario])
        db.flush()
        source_table = SourceTable(project_id=project_id, business_system_id=system.id, table_code="CUST", table_name="客户主表")
        db.add(source_table)
        db.flush()
        target_field = TargetField(project_id=project_id, target_table_id=target_table.id, field_code="CUST_NO", field_name="客户统一编号")
        mart_field = MartField(project_id=project_id, mart_table_id=mart_table.id, field_code="CUST_NO", field_name="客户统一编号")
        source_field = SourceField(project_id=project_id, source_table_id=source_table.id, field_code="CUST_NO", field_name="客户编号")
        document = KnowledgeDocument(
            project_id=project_id, file_name="rule.md", file_type="md", source_type="upload",
            storage_path="projects/test/rule.md", file_hash="a" * 64,
        )
        db.add_all([target_field, mart_field, source_field, document])
        db.flush()
        version = KnowledgeDocumentVersion(
            project_id=project_id, document_id=document.id, version_no=1, file_name="rule.md",
            storage_path="projects/test/rule.md", file_hash="a" * 64,
        )
        db.add(version)
        db.flush()
        unit = KnowledgeUnit(
            project_id=project_id, document_id=document.id, document_version_id=version.id,
            knowledge_type="regulatory_rule", knowledge_scope="project", unit_type="paragraph",
            content="客户统一编号规则", normalized_content="客户统一编号规则", source_file_name="rule.md",
            content_hash="b" * 64,
        )
        db.add(unit)
        db.flush()
        source_to_mart = SourceToMartMapping(
            project_id=project_id, mart_field_id=mart_field.id, mapping_name="客户源到集市",
            business_rule="保留有效客户", final_content="源字段直接映射到集市字段",
        )
        mart_to_ybt = MartToYbtMapping(
            project_id=project_id, target_field_id=target_field.id, mart_field_id=mart_field.id,
            mapping_name="客户集市到报送", business_rule="按监管口径映射", final_content="集市字段映射到报送字段",
        )
        business_mapping = ScenarioBusinessMapping(
            project_id=project_id, target_field_id=target_field.id, scenario_id=scenario.id,
            business_definition="客户统一编号业务口径", final_content="客户唯一识别",
        )
        technical_lineage = ScenarioTechnicalLineage(
            project_id=project_id, target_field_id=target_field.id, scenario_id=scenario.id,
            source_system_name="ECIF", source_table_chinese_name="客户主表",
            source_field_chinese_name="客户编号", processing_logic="清洗后取客户编号",
            final_content="客户编号血缘", lineage_status="linked",
        )
        db.add_all([source_to_mart, mart_to_ybt, business_mapping, technical_lineage])
        db.commit()
        return {
            "target_table": target_table.id,
            "target_field": target_field.id,
            "mart_table": mart_table.id,
            "mart_field": mart_field.id,
            "source_table": source_table.id,
            "source_field": source_field.id,
            "scenario": scenario.id,
            "knowledge_unit": unit.id,
            "source_to_mart_mapping": source_to_mart.id,
            "mart_to_ybt_mapping": mart_to_ybt.id,
            "scenario_business_mapping": business_mapping.id,
            "scenario_technical_lineage": technical_lineage.id,
        }


@contextmanager
def _semantic_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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


def _post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()
