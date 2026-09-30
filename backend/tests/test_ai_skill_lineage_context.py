from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.models import (BusinessSystem, CatalogColumn, CatalogSchema, CatalogTable, ColumnProfileSnapshot, ColumnProfileTask, DataSource,
                        Project, SourceField, SourceTable)
from app.schemas.ai_skill import SkillScope
from app.services.ai_skills.lineage_context import auxiliary_context
from test_ai_skill_control import control_env


def test_constraints_are_historical_project_scoped_and_missing_is_explicit(control_env):
    _, factory, _, scope, _ = control_env
    cutoff = datetime.now(timezone.utc)
    with factory() as db:
        project = db.get(Project, scope["project_id"])
        other = db.scalar(select(Project).where(Project.id != project.id))
        systems = [BusinessSystem(project_id=owner.id, system_code="fixed", system_name="fixed") for owner in (project, other)]
        db.add_all(systems); db.flush()
        tables = [SourceTable(project_id=owner.id, business_system_id=system.id, table_code="fixed", table_name="fixed")
                  for owner, system in zip((project, other), systems)]
        db.add_all(tables); db.flush()
        fields = [SourceField(project_id=owner.id, source_table_id=table.id, field_code="balance", field_name="余额",
                              field_type="DECIMAL(18,2)", updated_at=cutoff - timedelta(days=1))
                  for owner, table in zip((project, other), tables)]
        db.add_all(fields); db.flush()
        nodes = [{"node_key": "a", "source_field_id": fields[0].id}, {"node_key": "b", "source_field_id": fields[1].id}]
        revision = SimpleNamespace(id=10, created_at=cutoff, parent_revision_id=None)
        edge = {"source_node_key": "a", "target_node_key": "b"}
        facts, gaps = auxiliary_context(db, project, revision, nodes, edge, SkillScope.model_validate(scope), ["field_constraints", "script_diff"])
        assert len(facts) == 1 and facts[0].value["constraints"]["field_type"] == "DECIMAL(18,2)"
        assert {gap.code for gap in gaps} == {"historical_constraints_missing", "revision_baseline_missing"}
        fields[0].updated_at = cutoff + timedelta(days=1)
        db.flush()
        facts, gaps = auxiliary_context(db, project, revision, nodes, edge, SkillScope.model_validate(scope), ["field_constraints"])
        assert facts == [] and len(gaps) == 2


def test_quality_uses_old_snapshot_without_values_or_newer_observations(control_env):
    _, factory, _, scope, _ = control_env
    cutoff = datetime.now(timezone.utc)
    with factory() as db:
        project = db.get(Project, scope["project_id"])
        source = DataSource(project_id=project.id, name="synthetic", db_type="sqlite")
        db.add(source); db.flush()
        schema = CatalogSchema(project_id=project.id, datasource_id=source.id, schema_name="main")
        db.add(schema); db.flush()
        table = CatalogTable(project_id=project.id, datasource_id=source.id, catalog_schema_id=schema.id, schema_name="main", table_name="synthetic")
        db.add(table); db.flush()
        column = CatalogColumn(project_id=project.id, datasource_id=source.id, catalog_table_id=table.id,
                               schema_name="main", table_name="synthetic", column_name="balance")
        db.add(column); db.flush()
        task = ColumnProfileTask(project_id=project.id, datasource_id=source.id, catalog_column_id=column.id, status="succeeded")
        db.add(task); db.flush()
        rows = [ColumnProfileSnapshot(project_id=project.id, datasource_id=source.id, catalog_column_id=column.id,
            profile_task_id=task.id, profile_date=cutoff + timedelta(days=offset), total_count=count,
            top_values_json=[{"value": "PRIVATE_SAMPLE"}], min_value_text="PRIVATE_MIN", max_value_text="PRIVATE_MAX")
            for offset, count in ((-1, 100), (1, 999))]
        db.add_all(rows); db.flush()
        revision = SimpleNamespace(id=10, created_at=cutoff, parent_revision_id=None)
        nodes = [{"node_key": "a", "catalog_column_id": column.id}, {"node_key": "b"}]
        edge = {"source_node_key": "a", "target_node_key": "b"}
        facts, gaps = auxiliary_context(db, project, revision, nodes, edge, SkillScope.model_validate(scope), ["quality_profile"])
        assert len(facts) == 1 and facts[0].value["statistics"]["total_count"] == 100
        assert "PRIVATE" not in facts[0].model_dump_json()
        assert gaps[0].code == "historical_profile_missing"
        source.enabled = False; db.flush()
        facts, gaps = auxiliary_context(db, project, revision, nodes, edge, SkillScope.model_validate(scope), ["quality_profile"])
        assert facts == [] and len(gaps) == 2


def test_script_diff_keeps_fixed_parent_and_selected_endpoints(control_env):
    from app.models import LineageEdge, LineageRevision
    from app.services.lineage.revisions import LineageRevisionService
    from test_lineage_graph_contract import _seed_chain
    _, factory, _, _, _ = control_env
    with factory() as db:
        seed = _seed_chain(db, code="AUX_DIFF")
        project = db.get(Project, seed["project_id"])
        old = db.get(LineageRevision, seed["revision_id"])
        service = LineageRevisionService(db)
        _, edges = service.members(old)
        selected = edges[0]
        live_edge = db.get(LineageEdge, selected["lineage_edge_id"])
        live_edge.transformation_expression = "COALESCE(balance, 0)"
        db.flush()
        current = service.build(project.id, publish=False).revision
        db.flush()
        assert current.id != old.id
        nodes, new_edges = service.members(current)
        selected = next(edge for edge in new_edges if edge["lineage_edge_id"] == live_edge.id)
        scope = SkillScope(scope_type="project", institution_id=project.institution_id, project_id=project.id)
        facts, gaps = auxiliary_context(db, project, current, nodes, selected, scope, ["script_diff"])
        assert not gaps and len(facts) == 1
        assert facts[0].value["from_revision_id"] == old.id
        assert any(item["change_category"] == "transformation_changed" for item in facts[0].value["items"])
        assert service.members(old)[1][0]["transformation_expression"] != "COALESCE(balance, 0)"
        other_seed = _seed_chain(db, code="AUX_OTHER")
        current.parent_revision_id = other_seed["revision_id"]
        db.flush()
        facts, gaps = auxiliary_context(db, project, current, nodes, selected, scope, ["script_diff"])
        assert facts == [] and gaps[0].code == "revision_baseline_missing"


def test_prior_human_decisions_keep_actor_time_and_never_adopt_candidates(control_env):
    from app.models import Requirement, RequirementRevision, RequirementGenerationInput, RequirementGenerationItem, TargetField, TargetTable, User
    _, factory, _, scope, _ = control_env
    cutoff = datetime.now(timezone.utc)
    with factory() as db:
        project = db.get(Project, scope["project_id"])
        actor = db.scalar(select(User).where(User.username == "manager"))
        target = TargetTable(project_id=project.id, table_code="synthetic", table_name="synthetic")
        requirement = Requirement(project_id=project.id, name="隔离人工历史")
        db.add_all([target, requirement]); db.flush()
        field = TargetField(project_id=project.id, target_table_id=target.id, field_code="balance", field_name="余额")
        saved = RequirementRevision(project_id=project.id, requirement_id=requirement.id, content_version=1,
            scope_version=1, content_json={}, content_hash="synthetic")
        db.add_all([field, saved]); db.flush()
        frozen = RequirementGenerationInput(project_id=project.id, requirement_id=requirement.id, revision_id=saved.id,
            idempotency_key="isolated", request_hash="synthetic", input_hash="synthetic", input_json={}, created_by=actor.id)
        db.add(frozen); db.flush()
        item = RequirementGenerationItem(input_id=frozen.id, field_id=field.id, section="business", decision="adopted",
            decided_by=actor.id, decided_at=cutoff - timedelta(days=1), decision_reason="人工核验", adopted_content_version=2,
            candidate_json={"text": "PRIVATE_CANDIDATE_NOT_REQUESTED"})
        db.add(item); db.flush()
        revision = SimpleNamespace(id=10, created_at=cutoff, parent_revision_id=None)
        nodes = [{"node_key": "a", "target_field_id": field.id}, {"node_key": "b"}]
        edge = {"source_node_key": "a", "target_node_key": "b"}
        facts, gaps = auxiliary_context(db, project, revision, nodes, edge, SkillScope.model_validate(scope), ["prior_human_decisions"])
        assert not gaps and len(facts) == 1
        assert facts[0].value["decided_by"] == actor.id
        assert "PRIVATE_CANDIDATE" not in facts[0].model_dump_json()
        assert "不构成本次候选" in facts[0].value["interpretation"]
        assert db.get(Requirement, requirement.id).content_version == 0
        item.decided_at = cutoff + timedelta(days=1); db.flush()
        facts, gaps = auxiliary_context(db, project, revision, nodes, edge, SkillScope.model_validate(scope), ["prior_human_decisions"])
        assert facts == [] and gaps[0].code == "prior_human_decision_missing"


def test_fixed_statement_keeps_full_sql_classification_and_dynamic_parse_gap(control_env):
    from app.models import ScriptFile, ScriptFileVersion, SqlStatement, StoredFile, User
    _, factory, _, scope, _ = control_env
    with factory() as db:
        project = db.get(Project, scope["project_id"])
        actor = db.scalar(select(User).where(User.username == "manager"))
        stored = StoredFile(institution_id=project.institution_id, project_id=project.id, storage_key="synthetic-not-read",
            original_file_name="fixed.sql", content_type="text/plain", byte_size=10000, content_hash="synthetic",
            classification="restricted", created_by=actor.id)
        script = ScriptFile(project_id=project.id, institution_id=project.institution_id,
                            relative_path="fixed.sql", file_name="fixed.sql", file_type="sql")
        db.add_all([stored, script]); db.flush()
        version = ScriptFileVersion(project_id=project.id, script_file_id=script.id, version_no=1,
            file_hash="synthetic", normalized_hash="synthetic", raw_content_storage_file_id=stored.id)
        db.add(version); db.flush()
        text = "SELECT balance FROM synthetic;\n" * 300
        statement = SqlStatement(project_id=project.id, script_file_version_id=version.id, statement_index=1,
            statement_type="select", raw_sql_hash="synthetic", normalized_sql=text, parse_status="partially_parsed",
            warnings_json=["动态 SQL 尚未解析"])
        db.add(statement); db.flush()
        revision = SimpleNamespace(id=10, created_at=datetime.now(timezone.utc), parent_revision_id=None,
            source_manifest_json=[{"version_id": version.id, "file_hash": version.file_hash}])
        edge = {"source_node_key": "a", "target_node_key": "b", "script_file_version_id": version.id, "statement_id": statement.id}
        facts, gaps = auxiliary_context(db, project, revision, [], edge, SkillScope.model_validate(scope), ["script_evidence"])
        assert facts[0].value["normalized_sql"] == text
        assert facts[0].confidentiality == "restricted"
        assert {gap.code for gap in gaps} == {"parse_gap", "incomplete_script_parse"}
        revision.source_manifest_json[0]["file_hash"] = "wrong"
        facts, gaps = auxiliary_context(db, project, revision, [], edge, SkillScope.model_validate(scope), ["script_evidence"])
        assert facts == [] and gaps[0].code == "fixed_script_statement_missing"
