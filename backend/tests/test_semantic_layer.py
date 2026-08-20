from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
import threading

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.api.semantic import router as semantic_router
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
    SemanticConceptVersion,
    SemanticRelation,
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
from app.services.auth.dependencies import get_current_principal
from app.services.governance.workflow import decide_task, start_workflow
from app.services.semantic.entity_adapter import SemanticEntityAdapter
from app.services.semantic.graph_service import SemanticGraphService
from app.services.semantic.status_policy import (
    SemanticVisibilityMode,
    audit_only_statuses,
    candidate_statuses,
    is_visible,
    trusted_statuses,
)
from app.services.semantic.version_service import (
    _assert_confirmed_interval_available,
    create_concept_version,
    resolve_effective_version,
    sync_legacy_concept_projection,
    transition_version_status,
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
        assert updated.json()["version"] == 1


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
        for relation in created:
            confirmed = client.post(
                f"/api/projects/{project_id}/semantic-relations/{relation['id']}/status",
                json={"status": "confirmed"},
            )
            assert confirmed.status_code == 200, confirmed.text

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
            "entity_type": "target_field", "entity_id": field_id, "mode": "candidate",
        })
        second = _post(client, f"/api/projects/{project_id}/semantic-resolve", {
            "entity_type": "target_field", "entity_id": field_id, "mode": "candidate",
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
        assert first["candidates"][0]["evidence"][0]["source_id"] == binding["id"]


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


def test_temporal_version_resolution_is_inclusive_and_overlap_is_atomic() -> None:
    with _semantic_client() as (_, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            concept = SemanticConcept(
                project_id=project_id, concept_type="business_term", concept_code="TEMPORAL",
                concept_name="客户口径", status="confirmed", version=1,
            )
            db.add(concept)
            db.flush()
            v1 = create_concept_version(
                db, project_id=project_id, concept_id=concept.id, version_no=1,
                values={"concept_name": "2026客户口径", "status": "confirmed", "effective_from": date(2026, 1, 1), "effective_to": date(2026, 12, 31)},
            )
            v2 = create_concept_version(
                db, project_id=project_id, concept_id=concept.id, version_no=2,
                values={"concept_name": "2027客户口径", "status": "confirmed", "effective_from": date(2027, 1, 1), "effective_to": date(2027, 12, 31)},
            )
            db.commit()
            assert resolve_effective_version(db, concept.id, date(2026, 12, 31)).id == v1.id
            assert resolve_effective_version(db, concept.id, date(2027, 1, 1)).id == v2.id
            before = db.query(SemanticConceptVersion).count()
            try:
                _assert_confirmed_interval_available(db, concept.id, date(2026, 6, 1), date(2027, 2, 1))
            except Exception as error:
                assert getattr(error, "status_code", None) == 409
            else:
                raise AssertionError("overlap should be rejected")
            assert db.query(SemanticConceptVersion).count() == before


def test_sqlite_confirmed_interval_is_serialized_across_sessions() -> None:
    """Two concurrent SQLite writers cannot both confirm an overlapping interval."""

    from tempfile import TemporaryDirectory

    from sqlalchemy import create_engine

    with TemporaryDirectory() as directory:
        engine = create_engine(
            f"sqlite:///{directory}/semantic-concurrency.db",
            connect_args={"check_same_thread": False, "timeout": 0},
        )
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sessions() as db:
            institution = Institution(institution_code="LOCK_BANK", institution_name="锁测试机构")
            db.add(institution)
            db.flush()
            project = Project(name="锁测试项目", institution_id=institution.id)
            db.add(project)
            db.flush()
            concept = SemanticConcept(
                project_id=project.id, institution_id=institution.id,
                concept_type="business_term", concept_code="LOCKED", concept_name="并发口径",
            )
            db.add(concept)
            db.commit()
            concept_id = concept.id
            project_id = project.id

        start = threading.Barrier(2)
        first_writer_ready = threading.Event()
        release_first_writer = threading.Event()
        outcomes: list[str] = []
        errors: list[Exception] = []

        def writer(number: int) -> None:
            try:
                with sessions() as db:
                    start.wait(timeout=10)
                    if number == 0:
                        create_concept_version(
                            db, project_id=project_id, concept_id=concept_id,
                            values={
                                "status": "confirmed", "effective_from": date(2026, 1, 1),
                                "effective_to": date(2026, 12, 31),
                            },
                        )
                        first_writer_ready.set()
                        release_first_writer.wait(timeout=10)
                        db.commit()
                        outcomes.append("confirmed")
                        return
                    first_writer_ready.wait(timeout=10)
                    try:
                        create_concept_version(
                            db, project_id=project_id, concept_id=concept_id,
                            values={
                                "status": "confirmed", "effective_from": date(2026, 6, 1),
                                "effective_to": date(2027, 6, 30),
                            },
                        )
                    except Exception as exc:  # lock conflict is the expected concurrent outcome
                        db.rollback()
                        errors.append(exc)
                        return
                    db.commit()
                    outcomes.append("unexpected_second_confirmation")
            except Exception as exc:
                errors.append(exc)
            finally:
                if number == 0:
                    release_first_writer.set()

        first = threading.Thread(target=writer, args=(0,))
        second = threading.Thread(target=writer, args=(1,))
        first.start()
        second.start()
        first.join(timeout=20)
        second.join(timeout=20)

        assert not first.is_alive() and not second.is_alive()
        assert outcomes == ["confirmed"]
        assert errors
        assert any(getattr(error, "status_code", None) == 409 for error in errors)
        with sessions() as db:
            assert db.scalar(select(SemanticConceptVersion.status).where(
                SemanticConceptVersion.semantic_concept_id == concept_id,
                SemanticConceptVersion.status == "confirmed",
            )) == "confirmed"
            assert db.query(SemanticConceptVersion).filter_by(
                semantic_concept_id=concept_id, status="confirmed",
            ).count() == 1
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_version_inheritance_and_legacy_projection_preserve_confirmed_meaning() -> None:
    with _semantic_client() as (_, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            concept = SemanticConcept(
                project_id=project_id, concept_type="business_term", concept_code="INHERIT",
                concept_name="legacy name", definition="legacy definition", status="draft",
            )
            db.add(concept)
            db.flush()
            v1 = create_concept_version(
                db, project_id=project_id, concept_id=concept.id, version_no=1,
                values={
                    "concept_name": "v1 confirmed", "definition": "v1 definition",
                    "description": "v1 description", "aliases_json": ["v1 alias"],
                    "status": "confirmed", "effective_from": date(2026, 1, 1),
                    "effective_to": date(2026, 12, 31),
                }, created_by="reviewer",
            )
            db.commit()
            assert concept.concept_name == "v1 confirmed"
            assert concept.status == "confirmed"

            v2 = create_concept_version(
                db, project_id=project_id, concept_id=concept.id, version_no=2,
                values={
                    "concept_name": "v2 draft", "definition": "v2 definition",
                    "status": "draft", "effective_from": date(2027, 1, 1),
                    "effective_to": date(2027, 12, 31),
                }, created_by="author",
            )
            db.commit()
            assert concept.concept_name == "v1 confirmed"
            assert concept.definition == "v1 definition"
            assert concept.status == "confirmed"
            assert concept.version == 2

            v3 = create_concept_version(
                db, project_id=project_id, concept_id=concept.id, version_no=3,
                values={"description": "v3 description", "status": "draft"},
            )
            assert v3.concept_name == "v2 draft"
            assert v3.definition == "v2 definition"
            assert v3.aliases_json == ["v1 alias"]
            db.commit()
            assert concept.concept_name == "v1 confirmed"
            assert concept.description == "v1 description"
            assert concept.version == 3

            transition_version_status(db, v3, "rejected", "reviewer", project_id=project_id)
            db.commit()
            assert concept.concept_name == "v1 confirmed"
            assert concept.status == "confirmed"
            assert resolve_effective_version(db, concept.id, date(2026, 6, 1), project_id=project_id).id == v1.id

            v4 = create_concept_version(
                db, project_id=project_id, concept_id=concept.id, version_no=4,
                values={"description": "v4 description", "status": "draft"},
            )
            transition_version_status(db, v4, "deprecated", "reviewer", project_id=project_id)
            db.commit()
            assert concept.concept_name == "v1 confirmed"
            assert concept.status == "confirmed"
            assert concept.version == 4


def test_patch_latest_draft_is_allowed_after_prior_confirmed_projection() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        concept = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "PATCH_DRAFT",
            "concept_name": "已确认名称",
        })
        assert client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "confirmed"},
        ).status_code == 200
        created = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/versions",
            json={"concept_name": "待编辑草稿", "status": "draft", "effective_from": "2027-01-01"},
        )
        assert created.status_code == 201, created.text
        updated = client.patch(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}",
            json={"description": "草稿更新"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["concept_name"] == "已确认名称"
        with sessions() as db:
            latest = db.scalar(select(SemanticConceptVersion).where(
                SemanticConceptVersion.semantic_concept_id == concept["id"],
                SemanticConceptVersion.version_no == 2,
            ))
            assert latest is not None
            assert latest.description == "草稿更新"
            assert db.get(SemanticConcept, concept["id"]).status == "confirmed"


def test_shortest_path_respects_max_nodes_before_returning_neighbor() -> None:
    with _semantic_client() as (_, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            source = SemanticConcept(project_id=project_id, concept_type="business_term", concept_code="PATH_A", concept_name="A", status="confirmed")
            middle = SemanticConcept(project_id=project_id, concept_type="business_term", concept_code="PATH_B", concept_name="B", status="confirmed")
            target = SemanticConcept(project_id=project_id, concept_type="business_term", concept_code="PATH_C", concept_name="C", status="confirmed")
            db.add_all([source, middle, target])
            db.flush()
            db.add_all([
                SemanticRelation(project_id=project_id, source_concept_id=source.id, relation_type="related_to", target_concept_id=middle.id, status="confirmed"),
                SemanticRelation(project_id=project_id, source_concept_id=middle.id, relation_type="related_to", target_concept_id=target.id, status="confirmed"),
            ])
            db.commit()
            service = SemanticGraphService(db, project_id)
            assert service.shortest_path(source.id, target.id, max_nodes=2) == ([], [])
            assert service.shortest_path(source.id, target.id, max_nodes=3)[0] == [source.id, middle.id, target.id]


def test_knowledge_resolution_requires_manage_permission_and_hides_content_from_viewer() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        entities = _required_binding_entities(sessions, project_id)
        secret = "RESTRICTED_KNOWLEDGE_RAW_TEXT"
        with sessions() as db:
            unit = db.get(KnowledgeUnit, entities["knowledge_unit"])
            unit.content = secret
            unit.normalized_content = secret
            viewer = User(username="semantic_viewer")
            manager = User(username="semantic_knowledge_manager")
            db.add_all([viewer, manager])
            db.flush()
            db.add_all([
                ProjectMembership(project_id=project_id, user_id=viewer.id, project_role="viewer"),
                ProjectMembership(project_id=project_id, user_id=manager.id, project_role="knowledge_manager"),
            ])
            db.commit()
            viewer_id, viewer_username = viewer.id, viewer.username
            manager_id, manager_username = manager.id, manager.username

        app.dependency_overrides[get_current_principal] = lambda: Principal(viewer_id, viewer_username, None)
        denied = client.post(f"/api/projects/{project_id}/semantic-resolve", json={
            "entity_type": "knowledge_unit", "entity_id": entities["knowledge_unit"],
        })
        assert denied.status_code == 403
        assert secret not in denied.text

        app.dependency_overrides[get_current_principal] = lambda: Principal(manager_id, manager_username, None)
        allowed = client.post(f"/api/projects/{project_id}/semantic-resolve", json={
            "entity_type": "knowledge_unit", "entity_id": entities["knowledge_unit"],
        })
        assert allowed.status_code == 200, allowed.text


def test_graph_visibility_mode_filters_concept_binding_and_relation_together() -> None:
    with _semantic_client() as (_, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            confirmed = SemanticConcept(project_id=project_id, concept_type="business_term", concept_code="CONF", concept_name="确认", status="confirmed")
            draft = SemanticConcept(project_id=project_id, concept_type="business_term", concept_code="DRAFT", concept_name="草稿", status="draft")
            rejected = SemanticConcept(project_id=project_id, concept_type="business_term", concept_code="REJECT", concept_name="拒绝", status="rejected")
            db.add_all([confirmed, draft, rejected]); db.flush()
            db.add_all([
                SemanticRelation(project_id=project_id, source_concept_id=confirmed.id, relation_type="related_to", target_concept_id=draft.id, status="draft"),
                SemanticRelation(project_id=project_id, source_concept_id=confirmed.id, relation_type="is_a", target_concept_id=rejected.id, status="confirmed"),
            ])
            db.commit()
            service = SemanticGraphService(db, project_id)
            trusted_nodes = service.concepts({confirmed.id, draft.id, rejected.id})
            candidate_nodes = service.concepts({confirmed.id, draft.id, rejected.id}, mode=SemanticVisibilityMode.CANDIDATE)
            assert {item.id for item in trusted_nodes} == {confirmed.id}
            assert {item.id for item in candidate_nodes} == {confirmed.id, draft.id}
            trusted_depths, _, _ = service.traverse(confirmed.id)
            candidate_depths, _, _ = service.traverse(confirmed.id, mode=SemanticVisibilityMode.CANDIDATE)
            assert set(trusted_depths) == {confirmed.id}
            assert set(candidate_depths) == {confirmed.id, draft.id}


def test_additive_version_routes_preserve_concept_compatibility_and_static_precedence() -> None:
    effective_path = "/projects/{project_id}/semantic-concepts/{concept_id}/versions/effective"
    dynamic_path = "/projects/{project_id}/semantic-concepts/{concept_id}/versions/{version_id}"
    paths = [route.path for route in semantic_router.routes]
    assert paths.index(effective_path) < paths.index(dynamic_path)

    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        concept = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "VERSIONED",
            "concept_name": "原始监管口径", "status": "ai_suggested",
        })
        versions_path = f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/versions"
        listed = client.get(versions_path)
        assert listed.status_code == 200, listed.text
        assert [item["version_no"] for item in listed.json()] == [1]

        updated = client.patch(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}",
            json={"definition": "同一事务更新 canonical version"},
        )
        assert updated.status_code == 200, updated.text
        with sessions() as db:
            versions = db.scalars(select(SemanticConceptVersion).where(
                SemanticConceptVersion.semantic_concept_id == concept["id"],
            ).order_by(SemanticConceptVersion.version_no)).all()
            assert len(versions) == 1
            assert versions[0].definition == "同一事务更新 canonical version"

        confirmed = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "confirmed"},
        )
        assert confirmed.status_code == 200, confirmed.text
        locked = client.patch(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}",
            json={"definition": "不得覆盖已确认版本"},
        )
        assert locked.status_code == 409
        assert locked.json()["detail"]["code"] == "SEMANTIC_VERSION_IMMUTABLE"

        created = client.post(versions_path, json={
            "concept_name": "下一年度监管口径",
            "definition": "从 2027 年生效",
            "status": "draft",
            "effective_from": "2027-01-01",
        })
        assert created.status_code == 201, created.text
        version = created.json()
        detail = client.get(f"{versions_path}/{version['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["version_no"] == 2
        effective = client.get(f"{versions_path}/effective", params={"as_of": "2026-08-20"})
        assert effective.status_code == 200, effective.text
        assert effective.json()["version_no"] == 1


def test_semantic_graph_api_accepts_explicit_candidate_mode_without_changing_default() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        confirmed = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "ROOT_API", "concept_name": "根概念",
        })
        assert client.post(
            f"/api/projects/{project_id}/semantic-concepts/{confirmed['id']}/status",
            json={"status": "confirmed"},
        ).status_code == 200
        draft = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
            "concept_type": "business_term", "concept_code": "DRAFT_API", "concept_name": "候选概念",
        })
        _post(client, f"/api/projects/{project_id}/semantic-relations", {
            "source_concept_id": confirmed["id"], "relation_type": "related_to",
            "target_concept_id": draft["id"], "status": "draft",
        })
        trusted = client.get(
            f"/api/projects/{project_id}/semantic-concepts/{confirmed['id']}/neighbors",
        )
        candidate = client.get(
            f"/api/projects/{project_id}/semantic-concepts/{confirmed['id']}/neighbors",
            params={"mode": "candidate"},
        )
        assert trusted.status_code == 200, trusted.text
        assert candidate.status_code == 200, candidate.text
        assert {item["concept"]["id"] for item in trusted.json()["nodes"]} == {confirmed["id"]}
        assert {item["concept"]["id"] for item in candidate.json()["nodes"]} == {confirmed["id"], draft["id"]}


def _concept(client: TestClient, project_id: int, code: str, name: str) -> int:
    created = _post(client, f"/api/projects/{project_id}/semantic-concepts", {
        "concept_type": "business_term", "concept_code": code, "concept_name": name,
    })
    confirmed = client.post(
        f"/api/projects/{project_id}/semantic-concepts/{created['id']}/status",
        json={"status": "confirmed"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return created["id"]


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
