from datetime import UTC, date, datetime
from time import perf_counter

import pytest
from pydantic import ValidationError
from sqlalchemy import event, text

from app.main import app
from app.models import (
    AuditLog,
    BusinessSystem,
    MartTable,
    PendingQuestion,
    Project,
    ProjectMembership,
    ReviewTask,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    SemanticRelation,
    SourceTable,
    TargetTable,
    User,
    WorkflowInstance,
)
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.semantic.version_service import resolve_effective_versions
from app.schemas.semantic_catalog import (
    BoundedRegionMetadata,
    RestrictedSemanticDetailReference,
    SemanticBindingRegion,
    SemanticDetailConflictSummary,
    SemanticDetailRegionCapability,
    SemanticDetailReviewWorkflow,
    SemanticDetailShell,
)
try:
    # CI runs pytest from ``backend/`` while some local tooling runs from the
    # repository root; support both import roots without changing test logic.
    from tests.test_semantic_layer import (
        _post,
        _projects,
        _required_binding_entities,
        _semantic_client,
        _target_field,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by root-level pytest
    from backend.tests.test_semantic_layer import (
        _post,
        _projects,
        _required_binding_entities,
        _semantic_client,
        _target_field,
    )


def test_semantic_detail_dtos_keep_formal_temporal_and_governance_dimensions_explicit() -> None:
    shell = SemanticDetailShell(
        id=7,
        project_id=3,
        concept_type="business_term",
        concept_code="CUSTOMER_ID",
        concept_name="客户统一编号",
        lifecycle_status="ai_suggested",
        effective_as_of=date(2026, 8, 25),
        effective_version=None,
        review_workflow=SemanticDetailReviewWorkflow(
            pending=True,
            task_id=41,
            status="pending",
            current_step="business_review",
            href="/tasks/41?from=semantics&semanticConceptId=7",
        ),
        open_questions=[],
        conflicts=[
            SemanticDetailConflictSummary(
                conflict_key="definition",
                summary="两个高权威定义冲突",
                sources=[],
                review_href="/review-tasks?from=semantics&semanticConceptId=7",
            )
        ],
        regions={
            "bindings": SemanticDetailRegionCapability(temporal_scope="current_only"),
            "versions": SemanticDetailRegionCapability(temporal_scope="as_of"),
        },
    )

    assert shell.effective_version is None
    assert shell.lifecycle_status == "ai_suggested"
    assert shell.review_workflow.pending is True
    assert shell.conflicts[0].winner is None
    assert shell.regions["bindings"].temporal_scope == "current_only"

    with pytest.raises(ValidationError):
        SemanticDetailShell.model_validate({**shell.model_dump(), "legacy_definition": "forbidden"})


def test_semantic_lazy_region_dtos_have_explicit_partitions_and_bounded_metadata() -> None:
    region = SemanticBindingRegion(
        concept_id=7,
        as_of=date(2026, 8, 25),
        current_only=True,
        confirmed=[],
        candidates=[],
        audit=[],
        confirmed_meta=BoundedRegionMetadata(total=0, returned=0, limit=100),
        candidate_meta=BoundedRegionMetadata(total=0, returned=0, limit=100),
        audit_meta=BoundedRegionMetadata(total=0, returned=0, limit=100),
        chains=[],
        chain_meta=BoundedRegionMetadata(total=0, returned=0, limit=13),
    )

    assert region.confirmed == []
    assert region.candidates == []
    assert region.audit == []
    assert region.chain_meta.overflow == 0
    assert region.chain_meta.truncated is False

    with pytest.raises(ValidationError):
        BoundedRegionMetadata(total=2, returned=2, limit=1)


def test_restricted_semantic_detail_reference_cannot_accept_protected_fields() -> None:
    restricted = RestrictedSemanticDetailReference(
        entity_type="target_field",
        restricted=True,
    )
    assert restricted.model_dump() == {
        "entity_type": "target_field",
        "restricted": True,
    }

    for protected in (
        {"entity_id": 99},
        {"display_name": "秘密字段"},
        {"display_code": "SECRET"},
        {"href": "/fields/99/scenarios"},
        {"title": "秘密标题"},
        {"metadata": {"source": "hidden"}},
    ):
        with pytest.raises(ValidationError):
            RestrictedSemanticDetailReference.model_validate(
                {"entity_type": "target_field", "restricted": True, **protected}
            )


def test_semantic_detail_shell_and_lazy_routes_project_canonical_partitions() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        entities = _required_binding_entities(sessions, project_id)
        with sessions() as db:
            project = db.get(Project, project_id)
            concept, effective = _seed_concept(
                db,
                project,
                code="DETAIL_ROOT",
                name="详情根语义",
                definition="正式时态定义",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
            )
            related, _ = _seed_concept(
                db,
                project,
                code="DETAIL_RELATED",
                name="关联语义",
            )
            db.add(
                SemanticConceptVersion(
                    semantic_concept_id=concept.id,
                    project_id=project_id,
                    institution_id=project.institution_id,
                    version_no=2,
                    concept_name="候选详情根语义",
                    definition="AI 候选不能成为正式定义",
                    status="ai_suggested",
                    confidence_level="medium",
                    source_type="ai",
                    effective_from=date(2027, 1, 1),
                )
            )
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=concept.id,
                        entity_type="target_field",
                        entity_id=entities["target_field"],
                        binding_type="describes",
                        confidence_level="high",
                        status="confirmed",
                    ),
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=concept.id,
                        entity_type="source_field",
                        entity_id=entities["source_field"],
                        binding_type="candidate",
                        confidence_level="medium",
                        status="ai_suggested",
                    ),
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=concept.id,
                        target_concept_id=related.id,
                        relation_type="related_to",
                        confidence_level="high",
                        status="confirmed",
                    ),
                ]
            )
            target_table = TargetTable(
                project_id=project_id,
                table_code="DETAIL_QUESTION_TABLE",
                table_name="详情问题表",
            )
            workflow = WorkflowInstance(
                project_id=project_id,
                workflow_key="semantic_governance_review",
                target_type="semantic_concept",
                target_id=concept.id,
                status="in_progress",
                current_step="business_review",
                created_by=0,
            )
            db.add_all([target_table, workflow])
            db.flush()
            db.add_all(
                [
                    ReviewTask(
                        project_id=project_id,
                        workflow_instance_id=workflow.id,
                        step_key="business_review",
                        task_type="semantic_governance_review",
                        target_type="semantic_concept",
                        target_id=concept.id,
                        status="pending",
                    ),
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="high_authority_conflict",
                        question_text="两个正式来源冲突",
                        question_status="open",
                        priority="high",
                        source_type="semantic_concept",
                        source_id=concept.id,
                    ),
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="semantic",
                        question_text="已解决问题不得进入当前摘要",
                        question_status="accepted",
                        priority="medium",
                        source_type="semantic_concept",
                        source_id=concept.id,
                    ),
                ]
            )
            db.commit()
            concept_id, effective_id, related_id = concept.id, effective.id, related.id

        base = f"/api/projects/{project_id}/semantic-catalog/{concept_id}"
        shell = client.get(base, params={"as_of": "2026-12-31"})
        assert shell.status_code == 200, shell.text
        payload = shell.json()
        assert payload["effective_version"]["id"] == effective_id
        assert payload["effective_version"]["definition"] == "正式时态定义"
        assert payload["candidate_versions"][0]["definition"] == "AI 候选不能成为正式定义"
        assert payload["review_workflow"]["pending"] is True
        assert [item["question_text"] for item in payload["open_questions"]] == [
            "两个正式来源冲突"
        ]
        assert payload["conflicts"][0]["winner"] is None
        assert payload["regions"]["bindings"]["temporal_scope"] == "current_only"
        assert payload["regions"]["versions"]["temporal_scope"] == "as_of"

        for region in ("bindings", "relations", "evidence", "lineage", "governance", "versions"):
            response = client.get(f"{base}/{region}", params={"as_of": "2026-12-31"})
            assert response.status_code == 200, f"{region}: {response.text}"

        bindings = client.get(f"{base}/bindings").json()
        assert len(bindings["confirmed"]) == 1
        assert len(bindings["candidates"]) == 1
        assert bindings["audit"] == []
        assert bindings["chain_meta"]["limit"] == 13
        relations = client.get(f"{base}/relations").json()
        assert relations["confirmed"][0]["related_concept"]["entity_id"] == related_id
        versions = client.get(f"{base}/versions", params={"as_of": "2026-12-31"}).json()
        assert versions["effective_version_id"] == effective_id
        assert [item["status"] for item in versions["confirmed"]] == ["confirmed"]
        assert [item["status"] for item in versions["candidates"]] == ["ai_suggested"]


def test_semantic_detail_optional_permission_and_audit_routes_fail_closed() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        secret_name = "详情受限目标字段"
        target_id = _target_field(sessions, project_id, "DETAIL_SECRET", name=secret_name)
        with sessions() as db:
            project = db.get(Project, project_id)
            concept, _ = _seed_concept(db, project, code="DETAIL_SECURITY", name="详情安全语义")
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=concept.id,
                        entity_type="target_field",
                        entity_id=target_id,
                        status="confirmed",
                    ),
                    SemanticConceptVersion(
                        semantic_concept_id=concept.id,
                        project_id=project_id,
                        institution_id=project.institution_id,
                        version_no=2,
                        concept_name="已拒绝版本",
                        definition="审计内容",
                        status="rejected",
                        confidence_level="medium",
                        source_type="manual",
                        effective_from=date(2027, 1, 1),
                    ),
                ]
            )
            viewer = User(username="semantic_detail_viewer")
            db.add(viewer)
            db.flush()
            db.add(
                ProjectMembership(
                    project_id=project_id,
                    user_id=viewer.id,
                    project_role="viewer",
                    status="active",
                )
            )
            db.commit()
            concept_id, viewer_id, viewer_name = concept.id, viewer.id, viewer.username

        app.dependency_overrides[get_current_principal] = lambda: Principal(
            viewer_id, viewer_name, None
        )
        base = f"/api/projects/{project_id}/semantic-catalog/{concept_id}"
        bindings = client.get(f"{base}/bindings")
        assert bindings.status_code == 200, bindings.text
        assert bindings.json()["confirmed"][0]["target"] == {
            "entity_type": "target_field",
            "restricted": True,
        }
        assert secret_name not in bindings.text
        assert client.get(f"{base}/evidence").status_code == 403
        assert client.get(f"{base}/versions", params={"audit": "true"}).status_code == 403
        assert client.get(f"{base}/governance", params={"audit": "true"}).status_code == 403


def test_semantic_catalog_traces_canonical_effective_definition_and_confirmed_assets() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        target_field_id = _required_binding_entities(sessions, project_id)["target_field"]
        concept = _post(
            client,
            f"/api/projects/{project_id}/semantic-concepts",
            {
                "concept_type": "business_term",
                "concept_code": "CUST_NO",
                "concept_name": "客户统一编号",
                "definition": "由正式版本提供的客户统一编号定义",
                "business_domain": "客户",
                "owner_department": "数据治理部",
            },
        )
        confirmed = client.post(
            f"/api/projects/{project_id}/semantic-concepts/{concept['id']}/status",
            json={"status": "confirmed"},
        )
        assert confirmed.status_code == 200, confirmed.text

        with sessions() as db:
            db.get(SemanticConcept, concept["id"]).definition = "不得作为目录正式定义"
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=db.get(SemanticConcept, concept["id"]).institution_id,
                        semantic_concept_id=concept["id"],
                        entity_type="target_field",
                        entity_id=target_field_id,
                        binding_type="describes",
                        status="confirmed",
                    ),
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=db.get(SemanticConcept, concept["id"]).institution_id,
                        semantic_concept_id=concept["id"],
                        entity_type="target_field",
                        entity_id=target_field_id + 10_000,
                        binding_type="candidate",
                        status="ai_suggested",
                    ),
                    SemanticConcept(
                        project_id=project_id,
                        institution_id=db.get(SemanticConcept, concept["id"]).institution_id,
                        concept_type="business_term",
                        concept_code="REJECTED",
                        concept_name="已拒绝口径",
                        status="rejected",
                    ),
                ]
            )
            db.commit()

        response = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"as_of": date.today().isoformat()},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 1
        assert payload["page"] == 1
        assert payload["page_size"] == 50
        assert payload["mode"] == "candidate"
        assert payload["items"] == [
            {
                **payload["items"][0],
                "id": concept["id"],
                "project_id": project_id,
                "concept_code": "CUST_NO",
                "concept_name": "客户统一编号",
                "business_domain": "客户",
                "owner_department": "数据治理部",
                "related_asset_count": 1,
            }
        ]
        assert (
            payload["items"][0]["effective_version"]["definition"]
            == "由正式版本提供的客户统一编号定义"
        )
        assert "不得作为目录正式定义" not in response.text
        assert "REJECTED" not in response.text


def test_catalog_search_filters_and_audit_mode_are_server_authoritative() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        entities = _required_binding_entities(sessions, project_id)
        with sessions() as db:
            project = db.get(Project, project_id)
            confirmed, _ = _seed_concept(
                db,
                project,
                code="CLIENT_ID",
                name="客户标识",
                concept_type="business_term",
                domain="客户",
                owner="数据治理部",
                aliases=["统一客户号"],
                definition="监管统一标识定义",
            )
            draft, _ = _seed_concept(
                db,
                project,
                code="DRAFT_BALANCE",
                name="候选余额",
                concept_type="metric",
                domain="财务",
                owner="风险部",
                status="draft",
            )
            confirmed_related, _ = _seed_concept(
                db,
                project,
                code="CONFIRMED_RELATED",
                name="已确认关联语义",
            )
            rejected, _ = _seed_concept(
                db,
                project,
                code="REJECTED_RULE",
                name="已拒绝规则",
                status="rejected",
                version_status="rejected",
            )
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=confirmed.id,
                        entity_type="target_field",
                        entity_id=entities["target_field"],
                        status="confirmed",
                    ),
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=confirmed.id,
                        relation_type="related_to",
                        target_concept_id=draft.id,
                        status="confirmed",
                    ),
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=confirmed.id,
                        relation_type="uses",
                        target_concept_id=confirmed_related.id,
                        status="confirmed",
                    ),
                ]
            )
            workflow = WorkflowInstance(
                project_id=project_id,
                workflow_key="semantic_governance_review",
                target_type="semantic_concept",
                target_id=confirmed.id,
                status="in_progress",
                current_step="business_review",
                created_by=0,
            )
            db.add(workflow)
            db.flush()
            db.add(
                ReviewTask(
                    project_id=project_id,
                    workflow_instance_id=workflow.id,
                    step_key="business_review",
                    task_type="semantic_governance_review",
                    target_type="semantic_concept",
                    target_id=confirmed.id,
                    status="pending",
                )
            )
            db.commit()
            confirmed_id = confirmed.id
            confirmed_related_id = confirmed_related.id
            draft_id, rejected_id = draft.id, rejected.id

        for query in ("统一客户号", "监管统一标识"):
            searched = client.get(
                f"/api/projects/{project_id}/semantic-catalog", params={"q": query}
            )
            assert searched.status_code == 200, searched.text
            assert [item["id"] for item in searched.json()["items"]] == [confirmed_id]

        filtered = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={
                "type": "business_term",
                "domain": "客户",
                "owner": "数据治理部",
                "status": "confirmed",
                "has_binding": "true",
                "has_relation": "true",
                "pending_review": "true",
            },
        )
        assert filtered.status_code == 200, filtered.text
        assert [item["id"] for item in filtered.json()["items"]] == [confirmed_id]

        trusted = client.get(
            f"/api/projects/{project_id}/semantic-catalog", params={"mode": "trusted"}
        ).json()
        assert {item["id"] for item in trusted["items"]} == {
            confirmed_id,
            confirmed_related_id,
        }
        current = client.get(f"/api/projects/{project_id}/semantic-catalog").json()
        assert {item["id"] for item in current["items"]} == {
            confirmed_id,
            confirmed_related_id,
            draft_id,
        }
        audit = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"audit": "true", "status": "rejected"},
        )
        assert audit.status_code == 200, audit.text
        assert [item["id"] for item in audit.json()["items"]] == [rejected_id]


def test_catalog_totals_facets_pagination_order_and_counts_share_one_population() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            fixtures = [
                ("BETA", "乙概念", "B域"),
                ("ALPHA_2", "乙类", "A域"),
                ("UNCATEGORIZED", "未分类概念", None),
                ("ALPHA_1", "甲类", "A域"),
            ]
            concepts = [
                _seed_concept(db, project, code=code, name=name, domain=domain)[0]
                for code, name, domain in fixtures
            ]
            db.flush()
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=concepts[3].id,
                        entity_type="target_field",
                        entity_id=1001,
                        status="confirmed",
                    ),
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=concepts[3].id,
                        entity_type="target_field",
                        entity_id=1002,
                        status="draft",
                    ),
                ]
            )
            db.commit()

        first = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"mode": "trusted", "page": 1, "page_size": 2},
        )
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["total"] == 4
        assert payload["page"] == 1 and payload["page_size"] == 2
        assert [item["concept_code"] for item in payload["items"]] == [
            "ALPHA_1",
            "ALPHA_2",
        ]
        assert payload["items"][0]["related_asset_count"] == 1
        assert payload["facets"]["business_domains"] == {
            "A域": 2,
            "B域": 1,
            "__uncategorized__": 1,
        }
        second = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"mode": "trusted", "page": 2, "page_size": 2},
        ).json()
        assert [item["concept_code"] for item in second["items"]] == [
            "BETA",
            "UNCATEGORIZED",
        ]
        assert second["facets"] == payload["facets"]


def test_catalog_as_of_is_inclusive_and_ambiguity_is_a_safe_typed_error() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            concept, first = _seed_concept(
                db,
                project,
                code="TEMPORAL_CATALOG",
                name="时点口径",
                definition="边界均生效",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
            )
            db.commit()
            concept_id, first_id = concept.id, first.id

        for as_of in ("2026-01-01", "2026-12-31"):
            response = client.get(
                f"/api/projects/{project_id}/semantic-catalog",
                params={"mode": "trusted", "as_of": as_of},
            )
            assert response.status_code == 200, response.text
            assert response.json()["items"][0]["effective_version"]["id"] == first_id

        with sessions() as db:
            project = db.get(Project, project_id)
            db.add(
                SemanticConceptVersion(
                    semantic_concept_id=concept_id,
                    project_id=project_id,
                    institution_id=project.institution_id,
                    version_no=2,
                    concept_name="歧义版本",
                    definition="不得任意择优",
                    status="confirmed",
                    confidence_level="high",
                    source_type="manual",
                    effective_from=date(2026, 6, 1),
                    effective_to=date(2026, 12, 31),
                )
            )
            db.commit()

        ambiguous = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"mode": "trusted", "as_of": "2026-06-01"},
        )
        assert ambiguous.status_code == 409
        assert ambiguous.json()["detail"]["code"] == "SEMANTIC_VERSION_AMBIGUOUS"


def test_catalog_project_institution_scope_and_restricted_reference_are_safe() -> None:
    with _semantic_client() as (client, sessions):
        project_a, project_b = _projects(sessions)
        secret_name = "禁止泄露的目标字段名称"
        target_id = _target_field(sessions, project_a, "SECRET", name=secret_name)
        with sessions() as db:
            project = db.get(Project, project_a)
            foreign_institution = db.get(Project, project_b).institution_id
            visible, _ = _seed_concept(db, project, code="VISIBLE", name="可见概念")
            _seed_concept(
                db,
                project,
                code="WRONG_INSTITUTION",
                name="错误机构概念",
                institution_id=foreign_institution,
            )
            db.add(
                SemanticBinding(
                    project_id=project_a,
                    institution_id=project.institution_id,
                    semantic_concept_id=visible.id,
                    entity_type="target_field",
                    entity_id=target_id,
                    status="confirmed",
                )
            )
            viewer = User(username="semantic_catalog_viewer")
            db.add(viewer)
            db.flush()
            db.add(
                ProjectMembership(
                    project_id=project_a,
                    user_id=viewer.id,
                    project_role="viewer",
                    status="active",
                )
            )
            db.commit()
            viewer_id, viewer_name = viewer.id, viewer.username

        app.dependency_overrides[get_current_principal] = lambda: Principal(
            viewer_id, viewer_name, None
        )
        visible_response = client.get(
            f"/api/projects/{project_a}/semantic-catalog", params={"mode": "trusted"}
        )
        assert visible_response.status_code == 200, visible_response.text
        item = visible_response.json()["items"][0]
        assert item["related_assets"] == [
            {"entity_type": "target_field", "restricted": True}
        ]
        assert secret_name not in visible_response.text
        assert "entity_id" not in item["related_assets"][0]
        assert "WRONG_INSTITUTION" not in visible_response.text

        invisible = client.get(f"/api/projects/{project_b}/semantic-catalog")
        assert invisible.status_code == 404
        denied_audit = client.get(
            f"/api/projects/{project_a}/semantic-catalog", params={"audit": "true"}
        )
        assert denied_audit.status_code == 403


def test_catalog_and_detail_reject_same_project_foreign_institution_versions() -> None:
    with _semantic_client() as (client, sessions):
        project_id, project_b = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            foreign_institution_id = db.get(Project, project_b).institution_id
            concept, authorized_version = _seed_concept(
                db,
                project,
                code="FOREIGN_VERSION_SCOPE",
                name="机构隔离版本",
                definition="授权机构正式定义",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
            )
            foreign_version = SemanticConceptVersion(
                semantic_concept_id=concept.id,
                project_id=project_id,
                institution_id=foreign_institution_id,
                version_no=2,
                concept_name="外机构污染版本",
                definition="FOREIGN_INSTITUTION_FORMAL_DEFINITION",
                status="confirmed",
                confidence_level="high",
                source_type="manual",
                confirmed_by="foreign-reviewer",
                confirmed_at=datetime.now(UTC),
                effective_from=date(2027, 1, 1),
            )
            db.add(foreign_version)

            null_project = Project(name="无机构语义解析项目", institution_id=None)
            db.add(null_project)
            db.flush()
            null_concept, null_version = _seed_concept(
                db,
                null_project,
                code="NULL_INSTITUTION_VERSION_SCOPE",
                name="无机构正式版本",
                definition="仅显式空机构可见",
                effective_from=date(2027, 1, 1),
            )
            db.commit()
            concept_id = concept.id
            authorized_institution_id = project.institution_id
            foreign_version_id = foreign_version.id
            null_concept_id = null_concept.id
            null_version_id = null_version.id
            authorized_version_id = authorized_version.id

        catalog = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"mode": "trusted", "as_of": "2027-06-01"},
        )
        shell = client.get(
            f"/api/projects/{project_id}/semantic-catalog/{concept_id}",
            params={"as_of": "2027-06-01"},
        )
        assert catalog.status_code == 200, catalog.text
        assert shell.status_code == 200, shell.text
        catalog_item = next(
            item for item in catalog.json()["items"] if item["id"] == concept_id
        )
        assert catalog_item["effective_version"] is None
        assert shell.json()["effective_version"] is None
        assert "FOREIGN_INSTITUTION_FORMAL_DEFINITION" not in catalog.text
        assert "FOREIGN_INSTITUTION_FORMAL_DEFINITION" not in shell.text

        with sessions() as db:
            omitted = resolve_effective_versions(
                db, [concept_id], date(2027, 6, 1), project_id=project_id
            )
            integer_scoped = resolve_effective_versions(
                db,
                [concept_id],
                date(2027, 6, 1),
                project_id=project_id,
                institution_id=authorized_institution_id,
            )
            explicit_null = resolve_effective_versions(
                db,
                [null_concept_id, concept_id],
                date(2027, 6, 1),
                institution_id=None,
            )
            inclusive = resolve_effective_versions(
                db,
                [concept_id],
                date(2026, 12, 31),
                project_id=project_id,
                institution_id=authorized_institution_id,
            )

        assert omitted[concept_id].id == foreign_version_id
        assert concept_id not in integer_scoped
        assert explicit_null[null_concept_id].id == null_version_id
        assert concept_id not in explicit_null
        assert inclusive[concept_id].id == authorized_version_id


def test_foreign_institution_subordinate_rows_are_excluded_from_all_regions() -> None:
    with _semantic_client() as (client, sessions):
        project_id, project_b = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            foreign_institution_id = db.get(Project, project_b).institution_id
            root, root_version = _seed_concept(
                db, project, code="SUBORDINATE_SCOPE_ROOT", name="机构隔离根语义"
            )
            related, _ = _seed_concept(
                db, project, code="SUBORDINATE_SCOPE_RELATED", name="合法关联语义"
            )
            allowed_target = TargetTable(
                project_id=project_id,
                table_code="ALLOWED_SUBORDINATE_TARGET",
                table_name="合法机构目标表",
            )
            foreign_target = TargetTable(
                project_id=project_id,
                table_code="FOREIGN_SUBORDINATE_TARGET",
                table_name="FOREIGN_INSTITUTION_BINDING_TARGET",
            )
            db.add_all([allowed_target, foreign_target])
            db.flush()

            allowed_binding = SemanticBinding(
                project_id=project_id,
                institution_id=project.institution_id,
                semantic_concept_id=root.id,
                entity_type="target_table",
                entity_id=allowed_target.id,
                binding_type="describes",
                status="confirmed",
            )
            foreign_binding = SemanticBinding(
                project_id=project_id,
                institution_id=foreign_institution_id,
                semantic_concept_id=root.id,
                entity_type="target_table",
                entity_id=foreign_target.id,
                binding_type="describes",
                status="confirmed",
            )
            allowed_relation = SemanticRelation(
                project_id=project_id,
                institution_id=project.institution_id,
                source_concept_id=root.id,
                target_concept_id=related.id,
                relation_type="related_to",
                status="confirmed",
            )
            foreign_relation = SemanticRelation(
                project_id=project_id,
                institution_id=foreign_institution_id,
                source_concept_id=root.id,
                target_concept_id=related.id,
                relation_type="uses",
                status="confirmed",
            )
            foreign_candidate_version = SemanticConceptVersion(
                semantic_concept_id=root.id,
                project_id=project_id,
                institution_id=foreign_institution_id,
                version_no=2,
                concept_name="外机构候选版本",
                definition="FOREIGN_INSTITUTION_CANDIDATE_VERSION",
                status="ai_suggested",
                confidence_level="medium",
                source_type="ai",
                effective_from=date(2027, 1, 1),
            )
            foreign_audit_version = SemanticConceptVersion(
                semantic_concept_id=root.id,
                project_id=project_id,
                institution_id=foreign_institution_id,
                version_no=3,
                concept_name="外机构审计版本",
                definition="FOREIGN_INSTITUTION_AUDIT_VERSION",
                status="rejected",
                confidence_level="medium",
                source_type="manual",
                effective_from=date(2028, 1, 1),
            )
            db.add_all(
                [
                    allowed_binding,
                    foreign_binding,
                    allowed_relation,
                    foreign_relation,
                    foreign_candidate_version,
                    foreign_audit_version,
                ]
            )
            db.flush()

            allowed_question = PendingQuestion(
                project_id=project_id,
                institution_id=project.institution_id,
                target_table_id=allowed_target.id,
                question_type="high_authority_conflict",
                question_text="合法机构冲突问题",
                question_status="open",
                priority="high",
                source_type="semantic_concept",
                source_id=root.id,
            )
            foreign_question = PendingQuestion(
                project_id=project_id,
                institution_id=foreign_institution_id,
                target_table_id=foreign_target.id,
                question_type="high_authority_conflict",
                question_text="FOREIGN_INSTITUTION_PENDING_QUESTION",
                question_status="open",
                priority="high",
                source_type="semantic_concept",
                source_id=root.id,
            )
            allowed_audit = AuditLog(
                institution_id=project.institution_id,
                project_id=project_id,
                action="authorized_semantic_event",
                resource_type="semantic_concept",
                resource_id=str(root.id),
                result="success",
            )
            foreign_audit = AuditLog(
                institution_id=foreign_institution_id,
                project_id=project_id,
                action="FOREIGN_INSTITUTION_AUDIT_EVENT",
                resource_type="semantic_concept",
                resource_id=str(root.id),
                result="success",
            )
            db.add_all(
                [allowed_question, foreign_question, allowed_audit, foreign_audit]
            )
            db.commit()
            root_id = root.id
            root_version_id = root_version.id
            allowed_binding_id = allowed_binding.id
            foreign_binding_id = foreign_binding.id
            allowed_relation_id = allowed_relation.id
            foreign_relation_id = foreign_relation.id
            foreign_candidate_version_id = foreign_candidate_version.id
            foreign_audit_version_id = foreign_audit_version.id
            allowed_audit_id = allowed_audit.id
            foreign_audit_id = foreign_audit.id

        base = f"/api/projects/{project_id}/semantic-catalog/{root_id}"
        catalog = client.get(
            f"/api/projects/{project_id}/semantic-catalog", params={"mode": "trusted"}
        )
        shell = client.get(base)
        bindings = client.get(f"{base}/bindings", params={"audit": "true"})
        relations = client.get(f"{base}/relations", params={"audit": "true"})
        governance = client.get(f"{base}/governance", params={"audit": "true"})
        versions = client.get(f"{base}/versions", params={"audit": "true"})
        for response in (catalog, shell, bindings, relations, governance, versions):
            assert response.status_code == 200, response.text
            assert "FOREIGN_INSTITUTION" not in response.text

        catalog_item = next(
            item for item in catalog.json()["items"] if item["id"] == root_id
        )
        assert catalog_item["related_asset_count"] == 1
        assert catalog_item["has_relation"] is True
        assert catalog_item["open_question_count"] == 1
        assert shell.json()["effective_version"]["id"] == root_version_id
        assert shell.json()["candidate_versions"] == []
        assert [row["id"] for row in bindings.json()["confirmed"]] == [
            allowed_binding_id
        ]
        assert foreign_binding_id not in {
            row["id"] for partition in ("confirmed", "candidates", "audit")
            for row in bindings.json()[partition]
        }
        assert [row["id"] for row in relations.json()["confirmed"]] == [
            allowed_relation_id
        ]
        assert foreign_relation_id not in {
            row["id"] for partition in ("confirmed", "candidates", "audit")
            for row in relations.json()[partition]
        }
        assert [row["id"] for row in versions.json()["confirmed"]] == [
            root_version_id
        ]
        assert foreign_candidate_version_id not in {
            row["id"] for partition in ("confirmed", "candidates", "audit")
            for row in versions.json()[partition]
        }
        assert foreign_audit_version_id not in {
            row["id"] for partition in ("confirmed", "candidates", "audit")
            for row in versions.json()[partition]
        }
        assert [row["id"] for row in governance.json()["audit_events"]] == [
            allowed_audit_id
        ]
        assert foreign_audit_id not in {
            row["id"] for row in governance.json()["audit_events"]
        }


def test_confirmed_relation_aggregates_require_confirmed_same_institution_endpoints() -> None:
    with _semantic_client() as (client, sessions):
        project_id, project_b = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            foreign_institution_id = db.get(Project, project_b).institution_id
            root, _ = _seed_concept(
                db, project, code="RELATION_SCOPE_ROOT", name="关系聚合根语义"
            )
            confirmed, _ = _seed_concept(
                db, project, code="RELATION_SCOPE_CONFIRMED", name="合法已确认语义"
            )
            draft, _ = _seed_concept(
                db,
                project,
                code="RELATION_SCOPE_DRAFT",
                name="草稿端点语义",
                status="draft",
            )
            deprecated, _ = _seed_concept(
                db,
                project,
                code="RELATION_SCOPE_DEPRECATED",
                name="废弃端点语义",
                status="deprecated",
            )
            foreign, _ = _seed_concept(
                db,
                project,
                code="RELATION_SCOPE_FOREIGN",
                name="外机构端点语义",
                institution_id=foreign_institution_id,
            )
            db.add_all(
                [
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=root.id,
                        target_concept_id=confirmed.id,
                        relation_type="related_to",
                        status="confirmed",
                    ),
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=root.id,
                        target_concept_id=draft.id,
                        relation_type="uses",
                        status="confirmed",
                    ),
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=root.id,
                        target_concept_id=deprecated.id,
                        relation_type="part_of",
                        status="confirmed",
                    ),
                    SemanticRelation(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        source_concept_id=root.id,
                        target_concept_id=foreign.id,
                        relation_type="governed_by",
                        status="confirmed",
                    ),
                ]
            )
            db.commit()
            root_id = root.id
            confirmed_id = confirmed.id
            draft_id = draft.id

        catalog = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"mode": "candidate", "has_relation": "true"},
        )
        relations = client.get(
            f"/api/projects/{project_id}/semantic-catalog/{root_id}/relations"
        )
        assert catalog.status_code == 200, catalog.text
        assert relations.status_code == 200, relations.text
        relation_catalog_ids = {item["id"] for item in catalog.json()["items"]}
        assert root_id in relation_catalog_ids
        assert confirmed_id in relation_catalog_ids
        assert draft_id not in relation_catalog_ids
        assert [
            row["related_concept"]["entity_id"]
            for row in relations.json()["confirmed"]
        ] == [confirmed_id]


def test_catalog_review_questions_and_query_count_are_batched() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            concepts = [
                _seed_concept(
                    db,
                    project,
                    code=f"BATCH_{index}",
                    name=f"批量概念 {index}",
                )[0]
                for index in range(6)
            ]
            target_table = TargetTable(
                project_id=project_id,
                table_code="QUESTION_TABLE",
                table_name="问题表",
            )
            workflow = WorkflowInstance(
                project_id=project_id,
                workflow_key="semantic_governance_review",
                target_type="semantic_concept",
                target_id=concepts[0].id,
                status="in_progress",
                current_step="business_review",
                created_by=0,
            )
            db.add_all([target_table, workflow])
            db.flush()
            db.add_all(
                [
                    ReviewTask(
                        project_id=project_id,
                        workflow_instance_id=workflow.id,
                        step_key="business_review",
                        task_type="semantic_governance_review",
                        target_type="semantic_concept",
                        target_id=concepts[0].id,
                        status="pending",
                    ),
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="semantic",
                        question_text="当前仍待确认",
                        question_status="open",
                        source_type="semantic_concept",
                        source_id=concepts[0].id,
                    ),
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="semantic",
                        question_text="已经解决",
                        question_status="accepted",
                        source_type="semantic_concept",
                        source_id=concepts[0].id,
                    ),
                ]
            )
            db.commit()

        engine = sessions.kw["bind"]
        statements: list[str] = []

        def collect_statement(*args) -> None:
            statements.append(str(args[2]))

        event.listen(engine, "before_cursor_execute", collect_statement)
        try:
            one = client.get(
                f"/api/projects/{project_id}/semantic-catalog",
                params={"mode": "trusted", "page_size": 1},
            )
            assert one.status_code == 200, one.text
            one_count = len(statements)
            statements.clear()
            many = client.get(
                f"/api/projects/{project_id}/semantic-catalog",
                params={"mode": "trusted", "page_size": 6},
            )
            assert many.status_code == 200, many.text
            many_count = len(statements)
        finally:
            event.remove(engine, "before_cursor_execute", collect_statement)

        assert many_count <= one_count + 1
        first = many.json()["items"][0]
        assert first["review"]["pending"] is True
        assert first["review"]["pending_count"] == 1
        assert first["open_question_count"] == 1


def test_detail_isolation_distinguishes_visible_forbidden_and_hidden_projects() -> None:
    with _semantic_client() as (client, sessions):
        project_a, project_b = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_a)
            concept, _ = _seed_concept(
                db, project, code="DETAIL_SCOPE", name="详情权限边界"
            )
            visible_without_permission = User(username="semantic_visible_no_permission")
            db.add(visible_without_permission)
            db.flush()
            db.add(
                ProjectMembership(
                    project_id=project_a,
                    user_id=visible_without_permission.id,
                    project_role="unsupported_visible_role",
                    status="active",
                )
            )
            db.commit()
            concept_id = concept.id
            principal = Principal(
                visible_without_permission.id,
                visible_without_permission.username,
                None,
            )

        app.dependency_overrides[get_current_principal] = lambda: principal
        visible_forbidden = client.get(
            f"/api/projects/{project_a}/semantic-catalog/{concept_id}"
        )
        hidden_project = client.get(
            f"/api/projects/{project_b}/semantic-catalog/{concept_id}"
        )

        assert visible_forbidden.status_code == 403
        assert hidden_project.status_code == 404
        assert "DETAIL_SCOPE" not in hidden_project.text


def test_detail_temporal_candidate_and_question_lifecycle_are_canonical() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            confirmed, effective = _seed_concept(
                db,
                project,
                code="DETAIL_TEMPORAL",
                name="正式时态详情",
                definition="正式定义",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
            )
            ai_only, candidate = _seed_concept(
                db,
                project,
                code="DETAIL_AI_ONLY",
                name="仅 AI 候选",
                definition="候选定义不得升级为正式事实",
                status="ai_suggested",
                version_status="ai_suggested",
                effective_from=date(2026, 1, 1),
            )
            target_table = TargetTable(
                project_id=project_id,
                table_code="DETAIL_LIFECYCLE_QUESTION",
                table_name="详情问题生命周期表",
            )
            db.add(target_table)
            db.flush()
            db.add_all(
                [
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="semantic",
                        question_text="已分派仍未解决",
                        question_status="assigned",
                        source_type="semantic_concept",
                        source_id=confirmed.id,
                    ),
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="semantic",
                        question_text="已回答待验收仍未解决",
                        question_status="answered",
                        source_type="semantic_concept",
                        source_id=confirmed.id,
                    ),
                    PendingQuestion(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        target_table_id=target_table.id,
                        question_type="semantic",
                        question_text="已验收必须排除",
                        question_status="accepted",
                        source_type="semantic_concept",
                        source_id=confirmed.id,
                    ),
                ]
            )
            db.commit()
            confirmed_id, effective_id = confirmed.id, effective.id
            ai_only_id, candidate_id = ai_only.id, candidate.id

        confirmed_base = f"/api/projects/{project_id}/semantic-catalog/{confirmed_id}"
        for boundary in ("2026-01-01", "2026-12-31"):
            shell = client.get(confirmed_base, params={"as_of": boundary})
            assert shell.status_code == 200, shell.text
            assert shell.json()["effective_version"]["id"] == effective_id

        shell = client.get(confirmed_base, params={"as_of": "2026-06-01"}).json()
        assert [item["question_status"] for item in shell["open_questions"]] == [
            "assigned",
            "answered",
        ]
        assert "已验收必须排除" not in str(shell)

        ai_shell = client.get(
            f"/api/projects/{project_id}/semantic-catalog/{ai_only_id}",
            params={"as_of": "2026-06-01"},
        )
        assert ai_shell.status_code == 200, ai_shell.text
        assert ai_shell.json()["effective_version"] is None
        assert [row["id"] for row in ai_shell.json()["candidate_versions"]] == [
            candidate_id
        ]

        catalog = client.get(
            f"/api/projects/{project_id}/semantic-catalog",
            params={"mode": "trusted", "as_of": "2026-06-01"},
        )
        assert catalog.status_code == 200, catalog.text
        temporal_item = next(
            item for item in catalog.json()["items"] if item["id"] == confirmed_id
        )
        assert temporal_item["open_question_count"] == 2

        with sessions() as db:
            project = db.get(Project, project_id)
            db.add(
                SemanticConceptVersion(
                    semantic_concept_id=confirmed_id,
                    project_id=project_id,
                    institution_id=project.institution_id,
                    version_no=2,
                    concept_name="歧义详情版本",
                    definition="不得按浏览器顺序择优",
                    status="confirmed",
                    confidence_level="high",
                    source_type="manual",
                    effective_from=date(2026, 6, 1),
                    effective_to=date(2026, 12, 31),
                )
            )
            db.commit()

        ambiguous = client.get(confirmed_base, params={"as_of": "2026-06-01"})
        assert ambiguous.status_code == 409
        assert ambiguous.json()["detail"]["code"] == "SEMANTIC_VERSION_AMBIGUOUS"


def test_detail_audit_rows_are_isolated_and_successfully_marked_non_current() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            concept, confirmed = _seed_concept(
                db, project, code="DETAIL_AUDIT", name="审计隔离详情"
            )
            rejected_version = SemanticConceptVersion(
                semantic_concept_id=concept.id,
                project_id=project_id,
                institution_id=project.institution_id,
                version_no=2,
                concept_name="已拒绝历史版本",
                definition="仅审计可见",
                status="rejected",
                confidence_level="medium",
                source_type="manual",
                effective_from=date(2027, 1, 1),
            )
            rejected_binding = SemanticBinding(
                project_id=project_id,
                institution_id=project.institution_id,
                semantic_concept_id=concept.id,
                entity_type="target_table",
                entity_id=999_001,
                binding_type="describes",
                status="rejected",
            )
            db.add_all([rejected_version, rejected_binding])
            db.flush()
            db.add(
                AuditLog(
                    institution_id=project.institution_id,
                    project_id=project_id,
                    action="semantic_status_transition",
                    resource_type="semantic_concept",
                    resource_id=str(concept.id),
                    before_summary_json={"status": "draft"},
                    after_summary_json={"status": "rejected"},
                    result="success",
                )
            )
            db.commit()
            concept_id = concept.id
            confirmed_id = confirmed.id
            rejected_version_id = rejected_version.id
            rejected_binding_id = rejected_binding.id

        base = f"/api/projects/{project_id}/semantic-catalog/{concept_id}"
        trusted_versions = client.get(f"{base}/versions")
        trusted_bindings = client.get(f"{base}/bindings")
        assert trusted_versions.status_code == 200, trusted_versions.text
        assert trusted_bindings.status_code == 200, trusted_bindings.text
        assert [row["id"] for row in trusted_versions.json()["confirmed"]] == [
            confirmed_id
        ]
        assert trusted_versions.json()["audit"] == []
        assert trusted_bindings.json()["audit"] == []
        assert rejected_version_id not in {
            row["id"] for row in trusted_versions.json()["confirmed"]
        }
        assert rejected_binding_id not in {
            row["id"] for row in trusted_bindings.json()["confirmed"]
        }

        audit_versions = client.get(f"{base}/versions", params={"audit": "true"})
        audit_bindings = client.get(f"{base}/bindings", params={"audit": "true"})
        governance = client.get(f"{base}/governance", params={"audit": "true"})
        assert audit_versions.status_code == 200, audit_versions.text
        assert audit_bindings.status_code == 200, audit_bindings.text
        assert governance.status_code == 200, governance.text
        assert [row["id"] for row in audit_versions.json()["audit"]] == [
            rejected_version_id
        ]
        assert [row["id"] for row in audit_bindings.json()["audit"]] == [
            rejected_binding_id
        ]
        assert governance.json()["audit_events"][0]["status"] == "rejected"
        assert governance.json()["audit_events"][0]["non_current"] is True


def test_detail_chain_caps_each_family_and_reports_overflow_without_hidden_fields() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            concept, _ = _seed_concept(
                db, project, code="DETAIL_CHAIN_CAP", name="详情链路上限"
            )
            system = BusinessSystem(
                project_id=project_id,
                system_code="CHAIN_SOURCE_SYSTEM",
                system_name="链路源系统",
            )
            targets = [
                TargetTable(
                    project_id=project_id,
                    table_code=f"CHAIN_TARGET_{index}",
                    table_name=f"链路目标 {index}",
                )
                for index in range(5)
            ]
            marts = [
                MartTable(
                    project_id=project_id,
                    table_code=f"CHAIN_MART_{index}",
                    table_name=f"链路集市 {index}",
                )
                for index in range(5)
            ]
            db.add_all([system, *targets, *marts])
            db.flush()
            sources = [
                SourceTable(
                    project_id=project_id,
                    business_system_id=system.id,
                    table_code=f"CHAIN_SOURCE_{index}",
                    table_name=f"链路来源 {index}",
                )
                for index in range(5)
            ]
            db.add_all(sources)
            db.flush()
            db.add_all(
                [
                    SemanticBinding(
                        project_id=project_id,
                        institution_id=project.institution_id,
                        semantic_concept_id=concept.id,
                        entity_type=entity_type,
                        entity_id=row.id,
                        binding_type="describes",
                        status="confirmed",
                    )
                    for entity_type, rows in (
                        ("target_table", targets),
                        ("mart_table", marts),
                        ("source_table", sources),
                    )
                    for row in rows
                ]
            )
            viewer = User(username="semantic_chain_redaction_viewer")
            db.add(viewer)
            db.flush()
            db.add(
                ProjectMembership(
                    project_id=project_id,
                    user_id=viewer.id,
                    project_role="viewer",
                    status="active",
                )
            )
            db.commit()
            concept_id = concept.id
            viewer_principal = Principal(viewer.id, viewer.username, None)

        base = f"/api/projects/{project_id}/semantic-catalog/{concept_id}/bindings"
        readable = client.get(base)
        assert readable.status_code == 200, readable.text
        chain = readable.json()["chains"][0]
        assert [len(chain[family]) for family in ("targets", "marts", "sources")] == [
            4,
            4,
            4,
        ]
        assert readable.json()["chain_meta"] == {
            "total": 16,
            "returned": 13,
            "limit": 13,
            "overflow": 3,
            "truncated": True,
        }

        app.dependency_overrides[get_current_principal] = lambda: viewer_principal
        restricted = client.get(base)
        assert restricted.status_code == 200, restricted.text
        for binding in restricted.json()["confirmed"]:
            assert binding["target"] == {
                "entity_type": binding["target"]["entity_type"],
                "restricted": True,
            }
            assert not {
                "entity_id",
                "display_name",
                "display_code",
                "href",
                "title",
                "metadata",
            } & binding["target"].keys()


def test_uncategorized_facet_round_trips_null_and_blank_domains() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            _seed_concept(
                db,
                project,
                code="UNCATEGORIZED_NULL",
                name="空值未分类语义",
                domain=None,
            )
            _seed_concept(
                db,
                project,
                code="UNCATEGORIZED_BLANK",
                name="空白未分类语义",
                domain="   ",
            )
            _seed_concept(
                db,
                project,
                code="NAMED_DOMAIN",
                name="命名域语义",
                domain="客户",
            )
            db.commit()

        path = f"/api/projects/{project_id}/semantic-catalog"
        first = client.get(
            path,
            params={
                "mode": "trusted",
                "domain": "__uncategorized__",
                "page": 1,
                "page_size": 1,
            },
        )
        second = client.get(
            path,
            params={
                "mode": "trusted",
                "domain": "__uncategorized__",
                "page": 2,
                "page_size": 1,
            },
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        for payload in (first.json(), second.json()):
            assert payload["total"] == 2
            assert payload["facets"]["business_domains"] == {
                "__uncategorized__": 2
            }
            assert payload["page_size"] == 1
            assert "NAMED_DOMAIN" not in str(payload)
        assert [first.json()["items"][0]["concept_code"], second.json()["items"][0]["concept_code"]] == [
            "UNCATEGORIZED_BLANK",
            "UNCATEGORIZED_NULL",
        ]


def test_semantic_catalog_701_concepts_uses_existing_index_with_bounded_queries() -> None:
    with _semantic_client() as (client, sessions):
        project_id, _ = _projects(sessions)
        with sessions() as db:
            project = db.get(Project, project_id)
            concepts = [
                SemanticConcept(
                    project_id=project_id,
                    institution_id=project.institution_id,
                    concept_type="business_term",
                    concept_code=f"PERF_{index:04d}",
                    concept_name=f"性能语义 {index:04d}",
                    status="confirmed",
                    confidence_level="high",
                )
                for index in range(701)
            ]
            db.add_all(concepts)
            db.flush()
            db.add_all(
                [
                    SemanticConceptVersion(
                        semantic_concept_id=concept.id,
                        project_id=project_id,
                        institution_id=project.institution_id,
                        version_no=1,
                        concept_name=concept.concept_name,
                        definition=f"性能定义 {index:04d}",
                        status="confirmed",
                        confidence_level="high",
                        source_type="manual",
                        confirmed_by="performance-fixture",
                        confirmed_at=datetime.now(UTC),
                        effective_from=date(2026, 1, 1),
                    )
                    for index, concept in enumerate(concepts)
                ]
            )
            db.commit()
            query_plan = [
                str(row[-1])
                for row in db.execute(
                    text(
                        "EXPLAIN QUERY PLAN SELECT id FROM semantic_concepts "
                        "WHERE project_id = :project_id AND status IN "
                        "('confirmed', 'draft', 'ai_suggested') ORDER BY id LIMIT 100"
                    ),
                    {"project_id": project_id},
                ).all()
            ]

        path = f"/api/projects/{project_id}/semantic-catalog"
        params = {
            "mode": "trusted",
            "as_of": "2026-08-25",
            "page_size": 100,
        }
        warm = client.get(path, params=params)
        assert warm.status_code == 200, warm.text

        engine = sessions.kw["bind"]
        statements: list[str] = []

        def collect_statement(*args) -> None:
            statements.append(str(args[2]))

        event.listen(engine, "before_cursor_execute", collect_statement)
        started = perf_counter()
        try:
            response = client.get(path, params=params)
        finally:
            elapsed_ms = (perf_counter() - started) * 1000
            event.remove(engine, "before_cursor_execute", collect_statement)

        assert response.status_code == 200, response.text
        assert response.json()["total"] == 701
        assert len(response.json()["items"]) == 100
        assert len(statements) <= 12
        assert elapsed_ms < 2_000
        assert any(
            "USING INDEX" in detail and "project_id" in detail
            for detail in query_plan
        )
        print(
            "SEMANTIC_CATALOG_PERF_EVIDENCE "
            f"dialect=sqlite concepts=701 page_size=100 statements={len(statements)} "
            f"latency_ms={elapsed_ms:.2f} threshold_ms=2000 "
            f"plan={' | '.join(query_plan)}"
        )


def _seed_concept(
    db,
    project: Project,
    *,
    code: str,
    name: str,
    concept_type: str = "business_term",
    domain: str | None = None,
    owner: str | None = None,
    aliases: list[str] | None = None,
    definition: str | None = None,
    status: str = "confirmed",
    version_status: str | None = None,
    institution_id: int | None = None,
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = None,
):
    concept = SemanticConcept(
        project_id=project.id,
        institution_id=(project.institution_id if institution_id is None else institution_id),
        concept_type=concept_type,
        concept_code=code,
        concept_name=name,
        aliases_json=list(aliases or []),
        business_domain=domain,
        owner_department=owner,
        status=status,
        confidence_level="high",
    )
    db.add(concept)
    db.flush()
    version = SemanticConceptVersion(
        semantic_concept_id=concept.id,
        project_id=project.id,
        institution_id=concept.institution_id,
        version_no=1,
        concept_name=name,
        definition=definition,
        aliases_json=list(aliases or []),
        business_domain=domain,
        owner_department=owner,
        status=version_status or status,
        confidence_level="high",
        source_type="manual",
        confirmed_by="reviewer" if (version_status or status) == "confirmed" else None,
        confirmed_at=(
            datetime.now(UTC) if (version_status or status) == "confirmed" else None
        ),
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.add(version)
    db.flush()
    return concept, version
