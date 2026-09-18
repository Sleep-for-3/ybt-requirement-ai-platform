"""Candidate diff and explicit adoption for requirement-owned revisions."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib

from fastapi import HTTPException
from sqlalchemy import select

from app.models import RequirementGenerationInput, RequirementGenerationItem
from app.services.auth.permission_service import PermissionService
from app.services.requirement_gaps import reevaluate_field
from app.services.requirement_revisions import append_revision, load_revision, lock_requirement
from app.services.requirement_scope import content_digest, load_requirement


SECTION_FIELDS = {
    "business": ("business_definition", "final_content"),
    "lineage": ("processing_logic", "final_content"),
}
SPECIAL_FIELDS = {"lineage": ("physical_references", "evidence")}


def load_candidate_item(db, project_id, requirement_id, item_id, *, lock=False):
    statement = select(RequirementGenerationItem).join(
        RequirementGenerationInput, RequirementGenerationInput.id == RequirementGenerationItem.input_id
    ).where(RequirementGenerationItem.id == item_id,
        RequirementGenerationInput.project_id == project_id,
        RequirementGenerationInput.requirement_id == requirement_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(404, "候选不存在或不可见")
    generation_input = db.get(RequirementGenerationInput, item.input_id)
    if content_digest(generation_input.input_json) != generation_input.input_hash:
        raise HTTPException(409, "生成输入完整性检查失败")
    if item.status != "completed" or not item.candidate_json or not item.candidate_hash:
        raise HTTPException(409, "当前任务项尚无可处理候选")
    if content_digest(item.candidate_json) != item.candidate_hash:
        raise HTTPException(409, "候选完整性检查失败")
    return generation_input, item


def _record(content, field_id):
    record = next((row for row in content["fields"] if row["field"]["id"] == field_id), None)
    if record is None:
        raise HTTPException(409, "候选字段不在对应需求修订中")
    return record


def candidate_detail(db, project_id, requirement_id, item_id, principal):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    generation_input, item = load_candidate_item(db, project_id, requirement_id, item_id)
    revision = load_revision(db, project_id, requirement_id, generation_input.input_json["content_version"])
    requirement = load_requirement(db, project_id, requirement_id)
    record = _record(revision.content_json, item.field_id)
    candidate = item.candidate_json
    section = record.get(item.section) or {}
    ownership = revision.content_json.get("manual_ownership", {}).get(str(item.field_id), {})
    changes = []
    for field in SECTION_FIELDS[item.section]:
        proposed = candidate.get(field)
        if not isinstance(proposed, str) or not proposed.strip():
            continue
        current = section.get(field) or ""
        owner = ownership.get(f"{item.section}.{field}")
        changes.append({"field": field, "current": current, "proposed": proposed,
            "changed": current != proposed,
            "manual": bool(owner) and owner.get("kind", "manual") == "manual"})
    physical = []
    allowed_physical = {(row["kind"], row["table_id"], row["field_id"]): row
        for row in generation_input.input_json["physical_sources"]}
    for reference in candidate.get("physical_references", []):
        resolved = allowed_physical.get((reference.get("kind"), reference.get("table_id"), reference.get("field_id")))
        if resolved:
            physical.append({key: resolved.get(key) for key in (
                "kind", "table_id", "field_id", "table_code", "table_name", "field_code", "field_name", "field_type")})
    evidence_units = {row["unit_id"]: row for row in generation_input.input_json["evidence"]}
    evidence = [{"unit_id": unit_id, "document_id": evidence_units[unit_id]["document_id"],
        "title": evidence_units[unit_id].get("title") or "已选资料片段",
        "content": evidence_units[unit_id]["content"]}
        for unit_id in candidate.get("evidence_unit_ids", []) if unit_id in evidence_units]
    return {"id": item.id, "input_id": item.input_id, "field_id": item.field_id,
        "section": item.section, "candidate_hash": item.candidate_hash,
        "input_content_version": generation_input.input_json["content_version"],
        "current_content_version": requirement.content_version,
        "stale": requirement.content_version != generation_input.input_json["content_version"],
        "decision": item.decision, "decision_reason": item.decision_reason,
        "adopted_content_version": item.adopted_content_version,
        "changes": changes, "physical_references": physical, "evidence": evidence,
        "script_rules": [deepcopy(rule) for rule in generation_input.input_json.get("script_basis", {}).get("rules", [])
            if rule["rule_id"] in candidate.get("script_rule_ids", [])],
        "gaps": [str(value) for value in candidate.get("gaps", []) if str(value).strip()]}


def adopt_candidate(db, project_id, requirement_id, item_id, expected_version, candidate_hash,
                    selected_fields, replace_manual_fields, actor_id):
    return adopt_candidates(db, project_id, requirement_id, expected_version, [{
        "item_id": item_id, "candidate_hash": candidate_hash, "selected_fields": selected_fields,
        "replace_manual_fields": replace_manual_fields,
    }], actor_id)


def adopt_candidates(db, project_id, requirement_id, expected_version, selections, actor_id):
    requirement = lock_requirement(db, project_id, requirement_id)
    if not selections or len({selection["item_id"] for selection in selections}) != len(selections):
        raise HTTPException(422, "采用清单不能为空或包含重复候选")
    loaded = []
    for selection in sorted(selections, key=lambda value: value["item_id"]):
        generation_input, item = load_candidate_item(db, project_id, requirement_id, selection["item_id"], lock=True)
        if item.candidate_hash != selection["candidate_hash"]:
            raise HTTPException(409, "候选已变化，请重新查看差异")
        loaded.append((generation_input, item, selection))
    input_ids = {generation_input.id for generation_input, _, _ in loaded}
    if len(input_ids) != 1:
        raise HTTPException(422, "采用清单必须来自同一次固定生成输入")
    if all(item.decision == "adopted" for _, item, _ in loaded):
        versions = {item.adopted_content_version for _, item, _ in loaded}
        if len(versions) == 1 and requirement.content_version in versions:
            return load_revision(db, project_id, requirement_id, requirement.content_version), True
    if any(item.decision != "pending" for _, item, _ in loaded):
        raise HTTPException(409, "采用清单包含已经处理的候选")
    generation_input = loaded[0][0]
    input_version = generation_input.input_json["content_version"]
    if expected_version != input_version or requirement.content_version != input_version:
        raise HTTPException(409, "候选属于旧内容版本，请重新生成")
    previous = load_revision(db, project_id, requirement_id, input_version)
    if previous.status != "draft":
        raise HTTPException(409, "当前需求内容已锁定")
    content = deepcopy(previous.content_json)
    for current_input, item, selection in loaded:
        _apply_selection(content, current_input, item, selection["selected_fields"],
            selection.get("replace_manual_fields", []), actor_id, input_version + 1)
    revision = append_revision(db, requirement, content, input_version, actor_id)
    for _, item, _ in loaded:
        item.decision = "adopted"
        item.decision_reason = None
        item.decided_by = actor_id
        item.decided_at = datetime.now(UTC)
        item.adopted_content_version = revision.content_version
    db.flush()
    return revision, False


def _apply_selection(content, generation_input, item, selected_fields, replace_manual_fields, actor_id, next_version):
    allowed = set(SECTION_FIELDS[item.section]) | set(SPECIAL_FIELDS.get(item.section, ()))
    selected_fields = set(selected_fields)
    replace_manual_fields = set(replace_manual_fields)
    if not selected_fields or selected_fields - allowed or replace_manual_fields - selected_fields:
        raise HTTPException(422, "请选择有效候选差异")
    candidate = item.candidate_json
    record = _record(content, item.field_id)
    before = deepcopy(record)
    section = record.setdefault(item.section, {}) or {}
    record[item.section] = section
    ownership = content.setdefault("manual_ownership", {}).setdefault(str(item.field_id), {})
    valid = set()
    manual_conflicts = []
    for field in SECTION_FIELDS[item.section]:
        proposed = candidate.get(field)
        if field not in selected_fields or not isinstance(proposed, str) or not proposed.strip():
            continue
        valid.add(field)
        existing_owner = ownership.get(f"{item.section}.{field}")
        if existing_owner and existing_owner.get("kind", "manual") == "manual" and (section.get(field) or "") != proposed and field not in replace_manual_fields:
            manual_conflicts.append(field)
    if manual_conflicts:
        raise HTTPException(409, {"message": "候选会替换人工内容，请明确选择允许替换的字段",
                                  "manual_fields": sorted(manual_conflicts)})
    physical = []
    if "physical_references" in selected_fields:
        lookup = {(row["kind"], row["table_id"], row["field_id"]): row
            for row in generation_input.input_json["physical_sources"]}
        for reference in candidate.get("physical_references", []):
            resolved = lookup.get((reference.get("kind"), reference.get("table_id"), reference.get("field_id")))
            if resolved:
                physical.append({key: deepcopy(resolved.get(key)) for key in (
                    "kind", "table_id", "field_id", "table_code", "table_name", "field_code", "field_name", "field_type")})
        if physical:
            valid.add("physical_references")
    evidence = []
    if "evidence" in selected_fields:
        units = {row["unit_id"]: row for row in generation_input.input_json["evidence"]}
        for unit_id in candidate.get("evidence_unit_ids", []):
            if unit_id in units:
                unit = units[unit_id]
                evidence.append({"evidence_type": "knowledge_unit", "evidence_id": unit_id,
                    "source_name": unit.get("title") or "已选资料片段", "location_text": f"资料片段 {unit_id}",
                    "quoted_content": unit["content"], "evidence_summary": "需求生成候选引用"})
        if evidence:
            valid.add("evidence")
    if valid != selected_fields:
        raise HTTPException(422, "所选差异没有可采用内容")
    for field in SECTION_FIELDS[item.section]:
        if field in selected_fields:
            section[field] = candidate[field]
            ownership[f"{item.section}.{field}"] = {"kind": "ai_adopted", "actor_id": actor_id,
                "candidate_item_id": item.id, "content_version": next_version}
    if "physical_references" in selected_fields:
        section["physical_references"] = physical
        ownership[f"{item.section}.physical_references"] = {"kind": "ai_adopted", "actor_id": actor_id,
            "candidate_item_id": item.id, "content_version": next_version}
        content["lineage_graph"] = None
    if "evidence" in selected_fields:
        known = {(row.get("evidence_type"), row.get("evidence_id")) for row in record.get("evidence", [])}
        record["evidence"] = [*record.get("evidence", []),
            *(row for row in evidence if (row["evidence_type"], row["evidence_id"]) not in known)]
    section["business_confirm_status" if item.section == "business" else "tech_confirm_status"] = "draft"
    reevaluate_field(content, before, record, actor_id, next_version)
    for message in candidate.get("gaps", []):
        message = str(message).strip()
        if message:
            digest = hashlib.sha256(message.encode()).hexdigest()[:12]
            gap_id = f"candidate:{item.id}:{digest}"
            content["gaps"] = [gap for gap in content["gaps"] if gap["id"] != gap_id]
            content["gaps"].append({"id": gap_id, "field_id": item.field_id, "origin": "analysis",
                "status": "open", "message": message, "candidate_item_id": item.id})
    content["assessment"] = "gaps" if content["gaps"] else "clear"
    content.setdefault("candidate_adoptions", []).append({"item_id": item.id, "candidate_hash": item.candidate_hash,
        "input_id": item.input_id, "input_content_version": generation_input.input_json["content_version"], "selected_fields": sorted(selected_fields),
        "replaced_manual_fields": sorted(replace_manual_fields), "actor_id": actor_id})


def reject_candidate(db, project_id, requirement_id, item_id, candidate_hash, reason, actor_id):
    _, item = load_candidate_item(db, project_id, requirement_id, item_id, lock=True)
    if item.candidate_hash != candidate_hash:
        raise HTTPException(409, "候选已变化，请重新查看")
    if item.decision == "rejected":
        return item, True
    if item.decision != "pending":
        raise HTTPException(409, "候选已经处理")
    item.decision = "rejected"
    item.decision_reason = reason.strip()
    item.decided_by = actor_id
    item.decided_at = datetime.now(UTC)
    db.flush()
    return item, False
