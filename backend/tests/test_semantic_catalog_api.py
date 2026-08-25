from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from app.main import app
from app.models import (
    PendingQuestion,
    Project,
    ProjectMembership,
    ReviewTask,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    SemanticRelation,
    TargetTable,
    User,
    WorkflowInstance,
)
from app.services.auth.dependencies import Principal, get_current_principal
from app.schemas.semantic_catalog import (
    BoundedRegionMetadata,
    RestrictedSemanticDetailReference,
    SemanticBindingRegion,
    SemanticDetailConflictSummary,
    SemanticDetailRegionCapability,
    SemanticDetailReviewWorkflow,
    SemanticDetailShell,
)
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
            confirmed_id, draft_id, rejected_id = confirmed.id, draft.id, rejected.id

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
        assert {item["id"] for item in trusted["items"]} == {confirmed_id}
        current = client.get(f"/api/projects/{project_id}/semantic-catalog").json()
        assert {item["id"] for item in current["items"]} == {confirmed_id, draft_id}
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
