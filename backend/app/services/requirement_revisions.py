"""Append-only requirement-owned facts. No writes to shared mapping tables."""
from copy import deepcopy

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update

from app.models import Requirement, RequirementRevision
from app.services.requirement_scope import content_digest, live_document_content

EDITABLE = {
    "business": {"business_definition", "final_content", "business_owner", "remarks"},
    "lineage": {"source_system_name", "source_database_name", "source_schema_name",
        "source_table_english_name", "source_table_chinese_name", "source_field_english_name",
        "source_field_chinese_name", "processing_logic", "final_content", "tech_owner", "remarks"},
}


def scope_graph(graph, field_ids):
    from app.services.lineage.table_graph import bounded_paths
    graph = deepcopy(graph)
    roots = [f"asset:target_field:{field_id}" for field_id in sorted(field_ids)]
    selected, omitted = bounded_paths(roots, graph["edges"], "both", 4, 500)
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] in selected]
    graph["edges"] = [edge for edge in graph["edges"] if edge["source_node_id"] in selected and edge["target_node_id"] in selected]
    graph["tables"] = [{**table, "fields": [field for field in table["fields"] if field in selected],
                        "metadata_is_current": False} for table in graph["tables"] if set(table["fields"]) & selected]
    graph["root_ids"] = roots
    graph["truncated"] = graph["truncated"] or bool(omitted)
    graph["facts_mode"] = "requirement_import_snapshot"
    return graph


def reset_imported_status(record):
    record["imported_status"] = {"business": (record.get("business") or {}).get("business_confirm_status"),
        "technical": (record.get("lineage") or {}).get("tech_confirm_status")}
    if record.get("business"):
        record["business"]["business_confirm_status"] = "draft"
    if record.get("lineage"):
        record["lineage"]["tech_confirm_status"] = "draft"


def lock_requirement(db, project_id, requirement_id):
    row = db.scalar(select(Requirement).where(Requirement.id == requirement_id,
        Requirement.project_id == project_id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "需求不存在或不可见")
    return row


def load_revision(db, project_id, requirement_id, version):
    revision = db.scalar(select(RequirementRevision).where(
        RequirementRevision.project_id == project_id, RequirementRevision.requirement_id == requirement_id,
        RequirementRevision.content_version == version))
    if revision is None:
        raise HTTPException(404, "需求内容版本不存在或不可见")
    if content_digest(revision.content_json) != revision.content_hash:
        raise HTTPException(409, "内容版本完整性检查失败")
    return revision


def revision_document(revision):
    content = deepcopy(revision.content_json)
    if content.get("script_basis"):
        from app.services.requirement_paths import path_issues
        blocked = {i["field_id"] for i in path_issues(content)}
        for record in content["fields"]:
            record["path_confirmed"] = record["field"]["id"] not in blocked
    content.pop("lineage_graph", None)
    content["revision"] = {"content_version": revision.content_version,
        "scope_version": revision.scope_version, "parent_version": revision.parent_version,
        "status": revision.status, "created_at": revision.created_at.isoformat(),
        "content_hash": revision.content_hash}
    return content


def append_revision(db, requirement, content, expected, actor_id):
    result = db.execute(update(Requirement).where(Requirement.id == requirement.id,
        Requirement.project_id == requirement.project_id, Requirement.content_version == expected
    ).values(content_version=expected + 1))
    if result.rowcount != 1:
        raise HTTPException(409, "需求内容已变化，请重新加载后合并")
    content = deepcopy(jsonable_encoder(content))
    content.pop("revision", None)
    content["requirement"]["content_version"] = expected + 1
    content["status"] = "draft"
    row = RequirementRevision(project_id=requirement.project_id, requirement_id=requirement.id,
        content_version=expected + 1, scope_version=requirement.version, parent_version=expected or None,
        content_json=content, content_hash=content_digest(content), status="draft", created_by=actor_id)
    db.add(row)
    db.flush()
    return row


def initialize_content(db, requirement, expected_scope, actor_id, include_lineage=False):
    if requirement.version != expected_scope:
        raise HTTPException(409, "需求范围已变化，请重新加载")
    if requirement.content_version:
        return load_revision(db, requirement.project_id, requirement.id, requirement.content_version)
    content = jsonable_encoder(live_document_content(db, requirement))
    content["origin"] = {"kind": "shared_fact_import", "hash": content_digest(content)}
    content["manual_ownership"] = {}
    content["lineage_graph"] = None
    if include_lineage:
        from app.services.lineage.table_graph import table_graph
        graph = table_graph(db, requirement.project_id, "target", requirement.scope_json["target_table_id"])
        content["lineage_graph"] = scope_graph(graph, requirement.scope_json["field_ids"])
    # Imported confirmations describe the source, not approval of this new document.
    for record in content["fields"]:
        reset_imported_status(record)
    return append_revision(db, requirement, content, 0, actor_id)


def edit_field(db, requirement, version, field_id, section, changes, actor_id):
    if not requirement.content_version or requirement.content_version != version:
        raise HTTPException(409, "请重新加载当前需求内容版本")
    previous = load_revision(db, requirement.project_id, requirement.id, version)
    if previous.status != "draft":
        raise HTTPException(409, "当前版本已锁定，请通过修订流程建立新草稿")
    if section not in EDITABLE or not changes or set(changes) - EDITABLE[section]:
        raise HTTPException(422, "包含不可编辑字段")
    if any(value is not None and (not isinstance(value, str) or len(value) > 20000) for value in changes.values()):
        raise HTTPException(422, "字段内容格式错误或过长")
    content = deepcopy(previous.content_json)
    record = next((r for r in content["fields"] if r["field"]["id"] == field_id), None)
    if record is None:
        raise HTTPException(404, "字段不在当前需求范围内")
    before = deepcopy(record)
    mapping = record.setdefault(section, {}) or {}
    record[section] = mapping
    ownership = content.setdefault("manual_ownership", {}).setdefault(str(field_id), {})
    for key, value in changes.items():
        mapping[key] = value
        ownership[f"{section}.{key}"] = {"kind": "manual", "actor_id": actor_id, "content_version": version + 1}
    mapping["business_confirm_status" if section == "business" else "tech_confirm_status"] = "draft"
    from app.services.requirement_gaps import reevaluate_field
    reevaluate_field(content, before, record, actor_id, version + 1)
    if section == "lineage":
        content["lineage_graph"] = None
        # Changing text is not proof that a canonical field relationship exists.
        gap_id = f"{field_id}:edited_lineage"
        content["gaps"] = [g for g in content["gaps"] if g["id"] != gap_id]
        content["gaps"].append({"id": gap_id, "field_id": field_id, "origin": "analysis",
            "status": "open", "message": "技术口径已人工修改，需核验来源映射与血缘依据"})
    content["assessment"] = "gaps" if content["gaps"] else "clear"
    return append_revision(db, requirement, content, version, actor_id)


def revise_scope(db, requirement, previous, actor_id):
    content = jsonable_encoder(live_document_content(db, requirement))
    old = previous.content_json
    same_scenario = old["requirement"]["scenario_id"] == requirement.scope_json["scenario_id"]
    retained = {r["field"]["id"]: r for r in old["fields"]} if same_scenario else {}
    for record in content["fields"]:
        if record["field"]["id"] not in retained:
            reset_imported_status(record)
    content["fields"] = [deepcopy(retained.get(r["field"]["id"], r)) for r in content["fields"]]
    ids = {r["field"]["id"] for r in content["fields"]}
    content["gaps"] = [g for g in content["gaps"] if g["field_id"] not in retained]
    content["gaps"].extend(deepcopy([g for g in old["gaps"] if g["field_id"] in ids and g["field_id"] in retained]))
    content["manual_ownership"] = {key: deepcopy(value) for key, value in old.get("manual_ownership", {}).items()
        if int(key) in ids and int(key) in retained}
    content["gap_history"] = deepcopy([gap for gap in old.get("gap_history", [])
        if gap["field_id"] in ids and gap["field_id"] in retained])
    content["assessment"] = "gaps" if content["gaps"] else "clear"
    content["origin"] = deepcopy(old.get("origin", {}))
    if old.get("script_basis"):
        content["script_basis"] = deepcopy(old["script_basis"])
        if old.get("policy_comparisons"):
            content["policy_comparisons"] = deepcopy(old["policy_comparisons"])
        content["gaps"].extend(deepcopy([g for g in old["gaps"]
            if str(g.get("id", "")).startswith("scope:script:")]))
        confirmation = content["script_basis"]["confirmation"]
        if (confirmation["target_table_id"] != requirement.scope_json["target_table_id"]
                or set(confirmation["field_ids"]) != ids
                or set(old["requirement"].get("document_ids", [])) != set(requirement.scope_json.get("document_ids", []))
                or not same_scenario):
            content["gaps"].append({"id": "scope:script:scope_changed", "field_id": None,
                "origin": "analysis", "status": "open", "message": "需求范围已变化，须重新确认脚本目标与字段关联"})
            content["assessment"] = "gaps"
        if content["gaps"]:
            content["assessment"] = "gaps"
        from app.services.requirement_policy_comparison import sync_comparison_gaps
        sync_comparison_gaps(content)
    content["lineage_graph"] = scope_graph(old["lineage_graph"], ids) if same_scenario and ids <= set(retained) and old.get("lineage_graph") else None
    return append_revision(db, requirement, content, previous.content_version, actor_id)


def refresh_lineage(db, requirement, version, actor_id):
    """Refresh lineage graph from current assets and create new revision.

    Preserves field content, manual ownership, evidence, and gaps.
    Only updates lineage_graph snapshot and clears lineage-edit gaps.
    """
    if not requirement.content_version or requirement.content_version != version:
        raise HTTPException(409, "请重新加载当前需求内容版本")
    previous = load_revision(db, requirement.project_id, requirement.id, version)
    if previous.status != "draft":
        raise HTTPException(409, "当前版本已锁定，请通过修订流程建立新草稿")

    content = deepcopy(previous.content_json)
    field_ids = requirement.scope_json["field_ids"]

    # Re-query current asset graph
    from app.services.lineage.table_graph import table_graph
    try:
        current_graph = table_graph(db, requirement.project_id, "target", requirement.scope_json["target_table_id"])
        content["lineage_graph"] = scope_graph(current_graph, field_ids)
    except Exception:
        # If graph query fails, clear graph and add gap
        content["lineage_graph"] = None

    # Clear lineage-edit gaps since we just refreshed
    content["gaps"] = [g for g in content["gaps"] if not g["id"].endswith(":edited_lineage")]

    # Check for fields without lineage coverage and add gaps
    if content["lineage_graph"]:
        covered_fields = set()
        for node in content["lineage_graph"]["nodes"]:
            if node["id"].startswith("asset:target_field:"):
                covered_fields.add(int(node["id"].split(":")[-1]))

        for field_id in field_ids:
            if field_id not in covered_fields:
                gap_id = f"{field_id}:lineage_missing"
                # Remove existing gap if present
                content["gaps"] = [g for g in content["gaps"] if g["id"] != gap_id]
                content["gaps"].append({
                    "id": gap_id,
                    "field_id": field_id,
                    "origin": "analysis",
                    "status": "open",
                    "message": "当前资产图未覆盖此字段的血缘关系"
                })

    content["assessment"] = "gaps" if content["gaps"] else "clear"
    return append_revision(db, requirement, content, version, actor_id)
