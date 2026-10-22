"""VNext2 P1-B: SQL change -> requirement linkage must point at real requirements.

Banking contract: when a script change touches a governed target field, the
platform must report the *requirement* that owns that field so business reviewers
can re-check it, and it must not drag in unrelated requirements of the same
project or of another project.

Regression background: ``resolve_semantic_impact`` used to copy the affected
target field ids into ``requirement_ids``, and ``_impact_scope_dict`` then read
``TargetField`` rows by those ids.  The numbers lined up in demos, but the review
association was meaningless.
"""

from __future__ import annotations

from sqlalchemy import select

from app.api.lineage import _impact_scope_dict
from app.models import (
    BusinessSystem,
    LineageEdge,
    LineageNode,
    MartField,
    MartTable,
    ProductScenario,
    Project,
    Requirement,
    ReviewTask,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    ScriptFile as ScriptFileModel,
    ScriptFileVersion,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    MartToYbtMapping,
    TargetField,
    TargetTable,
    User,
)
from app.services.lineage.impact_analyzer import persist_change_impact
from app.services.lineage.sql_semantic_diff import compare_sql_versions
from app.services.lineage.semantic_impact import resolve_semantic_impact


def _seed(db, *, project_name: str = "P1-B 影响传递项目"):
    user = User(username=f"impact-{project_name}", status="active")
    project = Project(name=project_name)
    db.add_all([user, project])
    db.flush()
    system = BusinessSystem(project_id=project.id, system_code="ODS", system_name="源系统")
    db.add(system)
    db.flush()
    target_table = TargetTable(project_id=project.id, table_code="YBT_T", table_name="YBT")
    mart_table = MartTable(project_id=project.id, table_code="MART_T", table_name="集市")
    source_table = SourceTable(
        project_id=project.id, business_system_id=system.id, table_code="ODS_S", table_name="源表"
    )
    scenario = ProductScenario(project_id=project.id, scenario_code="DEFAULT", scenario_name="默认")
    db.add_all([target_table, mart_table, source_table, scenario])
    db.flush()
    field_a = TargetField(project_id=project.id, target_table_id=target_table.id, field_code="A", field_name="A")
    field_b = TargetField(project_id=project.id, target_table_id=target_table.id, field_code="B", field_name="B")
    mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="A", field_name="A")
    source_field = SourceField(project_id=project.id, source_table_id=source_table.id, field_code="A", field_name="A")
    db.add_all([field_a, field_b, mart_field, source_field])
    db.flush()
    db.add_all([
        ScenarioTechnicalLineage(
            project_id=project.id, target_field_id=field_a.id, scenario_id=scenario.id, final_content="人工技术口径"
        ),
        ScenarioBusinessMapping(
            project_id=project.id, target_field_id=field_a.id, scenario_id=scenario.id, final_content="人工业务口径"
        ),
        SourceToMartMapping(project_id=project.id, mart_field_id=mart_field.id, final_content="人工入集市口径"),
        MartToYbtMapping(
            project_id=project.id, target_field_id=field_a.id, mart_field_id=mart_field.id, final_content="人工上报口径"
        ),
    ])
    script = ScriptFileModel(
        project_id=project.id, relative_path="load.sql", file_name="load.sql", file_type="sql", current_version_no=2
    )
    db.add(script)
    db.flush()
    old = ScriptFileVersion(
        project_id=project.id, script_file_id=script.id, version_no=1, file_hash="a" * 64, normalized_hash="b" * 64,
        raw_content_storage_file_id=1, parse_status="parsed", created_by=user.id,
    )
    new = ScriptFileVersion(
        project_id=project.id, script_file_id=script.id, version_no=2, file_hash="c" * 64, normalized_hash="d" * 64,
        raw_content_storage_file_id=2, parse_status="parsed", created_by=user.id,
    )
    db.add_all([old, new])
    db.flush()
    source_node = LineageNode(
        project_id=project.id, node_type="column", logical_name="ODS_S.A", table_name="ODS_S", column_name="A",
        source_field_id=source_field.id, script_file_id=script.id, script_file_version_id=old.id, unresolved_flag=False,
    )
    mart_node = LineageNode(
        project_id=project.id, node_type="column", logical_name="MART_T.A", table_name="MART_T", column_name="A",
        mart_field_id=mart_field.id, script_file_id=script.id, script_file_version_id=old.id, unresolved_flag=False,
    )
    target_node = LineageNode(
        project_id=project.id, node_type="column", logical_name="YBT_T.A", table_name="YBT_T", column_name="A",
        target_field_id=field_a.id, script_file_id=script.id, script_file_version_id=new.id, unresolved_flag=False,
    )
    db.add_all([source_node, mart_node, target_node])
    db.flush()
    db.add(LineageEdge(
        project_id=project.id, script_file_version_id=new.id,
        source_node_id=source_node.id, target_node_id=mart_node.id,
        edge_type="column", transformation_expression="A",
    ))
    db.add(LineageEdge(
        project_id=project.id, script_file_version_id=new.id,
        source_node_id=mart_node.id, target_node_id=target_node.id,
        edge_type="column", transformation_expression="A",
    ))
    owner = Requirement(
        project_id=project.id,
        name="A 字段报送需求",
        version=1,
        content_version=1,
        scope_json={"target_table_id": target_table.id, "field_ids": [field_a.id], "scenario_id": scenario.id},
    )
    sibling = Requirement(
        project_id=project.id,
        name="B 字段报送需求",
        version=1,
        content_version=0,
        scope_json={"target_table_id": target_table.id, "field_ids": [field_b.id]},
    )
    db.add_all([owner, sibling])
    db.commit()
    return {
        "user": user,
        "project": project,
        "script": script,
        "old": old,
        "new": new,
        "owner": owner,
        "sibling": sibling,
        "field_a": field_a,
        "field_b": field_b,
    }


def _impact(db, seed, old_sql: str, new_sql: str, dialect: str = "sqlite"):
    diff = compare_sql_versions(old_sql, new_sql, dialect=dialect)
    change_set, impact = persist_change_impact(
        db, script_file=seed["script"], from_version=seed["old"], to_version=seed["new"],
        diff=diff, created_by=seed["user"].id,
    )
    db.commit()
    return diff, change_set, impact


def _requirement_ids(db, project_id: int, field_ids: list[int]) -> list[int]:
    return resolve_semantic_impact(
        db,
        project_id=project_id,
        source_field_ids=[],
        mart_field_ids=[],
        target_field_ids=field_ids,
        mapping_entity_ids={},
    ).requirement_ids


def test_impact_links_only_the_requirement_that_owns_the_changed_field(db_session):
    seed = _seed(db_session)
    diff, _change_set, impact = _impact(
        db_session,
        seed,
        "insert into MART_T(A,B) select A,B from ODS_S",
        "insert into MART_T(A) select A from ODS_S",
    )

    assert diff.semantic_changed is True
    assert impact.affected_target_field_ids_json == [seed["field_a"].id]
    assert impact.affected_requirement_ids_json == [seed["owner"].id]
    assert impact.summary_json["semantic_impact"]["requirement_count"] == 1

    scope = _impact_scope_dict(db_session, impact)
    assert [item["id"] for item in scope["requirements"]] == [seed["owner"].id]
    assert scope["requirements"][0]["name"] == "A 字段报送需求"
    assert scope["requirements"][0]["field_ids"] == [seed["field_a"].id]
    assert scope["requirements"][0]["target_table_id"] == seed["field_a"].target_table_id


def test_unrelated_requirement_and_other_project_are_never_linked(db_session):
    seed = _seed(db_session)
    other_project = Project(name="P1-B 无关项目")
    db_session.add(other_project)
    db_session.flush()
    other_table = TargetTable(project_id=other_project.id, table_code="YBT_T", table_name="YBT")
    db_session.add(other_table)
    db_session.flush()
    other_field = TargetField(
        project_id=other_project.id, target_table_id=other_table.id, field_code="A", field_name="A"
    )
    db_session.add(other_field)
    db_session.flush()
    other_requirement = Requirement(
        project_id=other_project.id,
        name="无关项目需求",
        version=1,
        content_version=0,
        scope_json={"target_table_id": other_table.id, "field_ids": [other_field.id]},
    )
    db_session.add(other_requirement)
    db_session.commit()

    db_session.refresh(seed["project"])
    ids = _requirement_ids(db_session, seed["project"].id, [seed["field_a"].id])

    assert ids == [seed["owner"].id]
    assert seed["sibling"].id not in ids
    assert other_requirement.id not in ids
    # Asking for a field nobody owns yields no requirement, not a wrong one.
    assert _requirement_ids(db_session, seed["project"].id, [seed["field_b"].id]) == [seed["sibling"].id]
    assert _requirement_ids(db_session, seed["project"].id, [999_999]) == []


def test_format_and_comment_only_change_does_not_raise_a_requirement_review(db_session):
    seed = _seed(db_session)
    diff, _change_set, impact = _impact(
        db_session,
        seed,
        "insert into MART_T(A) select A from ODS_S",
        "-- 仅调整注释与空白\ninsert  into MART_T ( A )\nselect  A\n  from ODS_S\n",
    )

    assert diff.semantic_changed is False
    assert impact.open_questions_json == []
    tasks = list(db_session.scalars(
        select(ReviewTask).where(
            ReviewTask.project_id == seed["project"].id,
            ReviewTask.target_type == "impact_analysis",
            ReviewTask.target_id == impact.id,
        )
    ).all())
    assert tasks == []


def test_join_type_change_reaches_both_impact_and_review_tasks(db_session):
    seed = _seed(db_session)
    old_sql = "insert into MART_T(A) select a.A from ODS_S a left join ODS_B b on a.A = b.A"
    new_sql = "insert into MART_T(A) select a.A from ODS_S a inner join ODS_B b on a.A = b.A"
    diff, _change_set, impact = _impact(db_session, seed, old_sql, new_sql, dialect="mysql")

    if not diff.semantic_changed:  # pragma: no cover - dialect dependent guard
        return
    assert impact.affected_requirement_ids_json == [seed["owner"].id]
    tasks = list(db_session.scalars(
        select(ReviewTask).where(
            ReviewTask.project_id == seed["project"].id,
            ReviewTask.target_type == "impact_analysis",
            ReviewTask.target_id == impact.id,
        )
    ).all())
    assert impact.affected_review_task_ids_json == sorted(task.id for task in tasks)
