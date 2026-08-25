from datetime import UTC, date, datetime

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
from backend.tests.test_semantic_layer import (
    _post,
    _projects,
    _required_binding_entities,
    _semantic_client,
    _target_field,
)


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
        assert str(target_id) not in visible_response.text
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
