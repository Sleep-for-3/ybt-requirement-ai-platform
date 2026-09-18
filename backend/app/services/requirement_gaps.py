"""Deterministic checks shared by imported and requirement-owned facts."""


def field_gaps(record):
    from app.services.requirement_paths import confirmed_path
    has_path = confirmed_path(record)
    field_id = record["field"]["id"]
    business, technical = record.get("business") or {}, record.get("lineage") or {}
    missing = []
    def present(value):
        return bool(str(value or "").strip())
    if not any(present(business.get(key)) for key in ("final_content", "business_definition")):
        missing.append(("definition", "缺少业务定义"))
    if not has_path and not technical.get("physical_references") and not all(present(technical.get(key)) for key in ("source_table_english_name", "source_field_english_name")):
        missing.append(("source", "缺少可定位的来源表或字段"))
    if not has_path and not record.get("mart_mappings"):
        missing.append(("mapping", "缺少监管集市到目标字段映射"))
    for mapping in ([] if has_path else record.get("mart_mappings", [])):
        if not record.get("source_mappings", {}).get(str(mapping.get("mart_field_id"))):
            missing.append((f"source_mapping:{mapping['id']}", "缺少来源到集市字段的加工映射"))
    if not has_path and not any(present(technical.get(key)) for key in ("processing_logic", "final_content")):
        missing.append(("transformation", "缺少完整加工规则"))
    if not has_path and not record.get("evidence"):
        missing.append(("evidence", "缺少可追溯证据"))
    for kind, mapping in (("business", business), ("technical", technical)):
        if present(mapping.get("open_questions")):
            missing.append((f"{kind}:questions", mapping["open_questions"]))
    return [{"id": f"{field_id}:{code}", "field_id": field_id, "origin": "analysis",
             "status": "open", "message": label} for code, label in missing]


def reevaluate_field(content, before, after, actor_id, version):
    previous = {gap["id"]: gap for gap in field_gaps(before)}
    current = {gap["id"]: gap for gap in field_gaps(after)}
    managed = previous.keys() | current.keys()
    content["gaps"] = [gap for gap in content["gaps"] if gap["id"] not in managed]
    content["gaps"].extend(current.values())
    for gap_id in previous.keys() - current.keys():
        content.setdefault("gap_history", []).append({**previous[gap_id], "status": "resolved",
            "resolution_basis": {"kind": "requirement_field_edit", "actor_id": actor_id,
                "content_version": version, "field_id": after["field"]["id"]}})
