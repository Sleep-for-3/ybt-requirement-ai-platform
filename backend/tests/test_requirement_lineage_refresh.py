"""Test requirement lineage refresh: re-verify current asset relationships."""
import pytest
from app.models import Requirement, ProductScenario
from app.services.requirement_revisions import refresh_lineage, initialize_content, load_revision
from app.services.requirement_scope import content_digest
from test_lineage_paths import _seed_assets


def test_refresh_lineage_updates_graph_and_creates_new_revision(db_session):
    """Refresh lineage from current assets creates new revision with updated graph."""
    user, _, project, field, _, _ = _seed_assets(db_session)
    scenario = ProductScenario(project_id=project.id, scenario_code="TEST", scenario_name="测试场景")
    db_session.add(scenario)
    db_session.flush()

    requirement = Requirement(
        project_id=project.id,
        name="测试需求",
        version=1,
        scope_json={
            "target_table_id": field.target_table_id,
            "scenario_id": scenario.id,
            "field_ids": [field.id],
        },
    )
    db_session.add(requirement)
    db_session.flush()

    # Initialize content with lineage
    revision_v1 = initialize_content(db_session, requirement, 1, user.id, include_lineage=True)
    assert revision_v1.content_version == 1
    original_graph = revision_v1.content_json.get("lineage_graph")

    # Refresh lineage
    revision_v2 = refresh_lineage(db_session, requirement, 1, user.id)
    db_session.flush()

    # Verify new revision created
    assert revision_v2.content_version == 2
    assert revision_v2.parent_version == 1
    assert revision_v2.status == "draft"

    # Verify graph was refreshed
    new_graph = revision_v2.content_json.get("lineage_graph")
    assert new_graph is not None
    assert "nodes" in new_graph
    assert "edges" in new_graph

    # Verify old revision unchanged
    old_revision = load_revision(db_session, project.id, requirement.id, 1)
    assert old_revision.content_json.get("lineage_graph") == original_graph


def test_refresh_lineage_clears_edited_lineage_gaps(db_session):
    """Refresh lineage clears lineage-edit gaps since graph is now current."""
    user, _, project, field, _, _ = _seed_assets(db_session)
    scenario = ProductScenario(project_id=project.id, scenario_code="TEST", scenario_name="测试场景")
    db_session.add(scenario)
    db_session.flush()

    requirement = Requirement(
        project_id=project.id,
        name="测试需求",
        version=1,
        scope_json={
            "target_table_id": field.target_table_id,
            "scenario_id": scenario.id,
            "field_ids": [field.id],
        },
    )
    db_session.add(requirement)
    db_session.flush()

    revision_v1 = initialize_content(db_session, requirement, 1, user.id, include_lineage=True)

    # Manually add an edited_lineage gap
    content = revision_v1.content_json
    content["gaps"].append({
        "id": f"{field.id}:edited_lineage",
        "field_id": field.id,
        "origin": "analysis",
        "status": "open",
        "message": "技术口径已人工修改，需核验来源映射与血缘依据"
    })
    revision_v1.content_json = content
    revision_v1.content_hash = content_digest(content)
    db_session.flush()

    # Refresh lineage
    revision_v2 = refresh_lineage(db_session, requirement, 1, user.id)
    db_session.flush()

    # Verify edited_lineage gap removed
    gaps = revision_v2.content_json.get("gaps", [])
    assert not any(g["id"].endswith(":edited_lineage") for g in gaps)


def test_refresh_lineage_preserves_field_content_and_ownership(db_session):
    """Refresh lineage preserves all field content, manual ownership, and evidence."""
    user, _, project, field, _, _ = _seed_assets(db_session)
    scenario = ProductScenario(project_id=project.id, scenario_code="TEST", scenario_name="测试场景")
    db_session.add(scenario)
    db_session.flush()

    requirement = Requirement(
        project_id=project.id,
        name="测试需求",
        version=1,
        scope_json={
            "target_table_id": field.target_table_id,
            "scenario_id": scenario.id,
            "field_ids": [field.id],
        },
    )
    db_session.add(requirement)
    db_session.flush()

    revision_v1 = initialize_content(db_session, requirement, 1, user.id, include_lineage=True)

    # Add manual content and ownership
    content = revision_v1.content_json
    content["fields"][0]["business"] = {
        "business_definition": "手工定义的业务含义",
        "business_confirm_status": "draft"
    }
    content["manual_ownership"] = {
        str(field.id): {
            "business.business_definition": {
                "kind": "manual",
                "actor_id": user.id,
                "content_version": 1
            }
        }
    }
    revision_v1.content_json = content
    revision_v1.content_hash = content_digest(content)
    db_session.flush()

    # Refresh lineage
    revision_v2 = refresh_lineage(db_session, requirement, 1, user.id)
    db_session.flush()

    # Verify field content preserved
    assert revision_v2.content_json["fields"][0]["business"]["business_definition"] == "手工定义的业务含义"

    # Verify manual ownership preserved
    ownership = revision_v2.content_json.get("manual_ownership", {}).get(str(field.id), {})
    assert "business.business_definition" in ownership
    assert ownership["business.business_definition"]["kind"] == "manual"


def test_refresh_lineage_requires_draft_status(db_session):
    """Cannot refresh lineage on locked (non-draft) revisions."""
    user, _, project, field, _, _ = _seed_assets(db_session)
    scenario = ProductScenario(project_id=project.id, scenario_code="TEST", scenario_name="测试场景")
    db_session.add(scenario)
    db_session.flush()

    requirement = Requirement(
        project_id=project.id,
        name="测试需求",
        version=1,
        scope_json={
            "target_table_id": field.target_table_id,
            "scenario_id": scenario.id,
            "field_ids": [field.id],
        },
    )
    db_session.add(requirement)
    db_session.flush()

    revision_v1 = initialize_content(db_session, requirement, 1, user.id, include_lineage=True)

    # Lock the revision
    revision_v1.status = "confirmed"
    db_session.flush()

    # Attempt to refresh lineage should fail
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        refresh_lineage(db_session, requirement, 1, user.id)
    assert exc.value.status_code == 409
    assert "已锁定" in exc.value.detail
