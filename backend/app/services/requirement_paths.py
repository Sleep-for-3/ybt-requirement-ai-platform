"""Confirmed field paths over immutable parser facts, independent of layer count."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.services.requirement_scope import content_digest


class ConfirmPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_version: int = Field(gt=0)
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale: str = Field(min_length=1, max_length=10000)


def identity(node):
    return (node.get("database_name"), node.get("schema_name"), node.get("table_name"), node.get("column_name"))


def technical_hash(record):
    return content_digest(record.get("lineage") or {})


def confirmed_path(record):
    path = record.get("confirmed_path") or {}
    return bool(path.get("confirmed_by") and path.get("rule_ids") and path.get("rationale")
        and path.get("technical_hash") == technical_hash(record))


def path_preview(content):
    from app.services.requirement_policy_comparison import basis_hash
    basis = content.get("script_basis")
    if not basis:
        raise HTTPException(409, "请先固定脚本依据和目标字段")
    incoming = defaultdict(list)
    for rule in basis["rules"]:
        incoming[identity(rule["target"])].append(rule)
    metadata = {t["id"]: t for t in basis["metadata"]}
    bindings = {value: key for key, value in basis["confirmation"]["field_bindings"].items()}
    target_key = basis["confirmation"]["target_key"]
    paths = []
    for record in content["fields"]:
        field_id = record["field"]["id"]
        column = bindings.get(field_id)
        roots = [r["target"] for r in basis["rules"]
            if r["target"]["table_key"] == target_key and r["target"].get("column_name") == column]
        issues, rules, nodes, leaves = set(), {}, {}, {}
        if not column or not roots:
            issues.add("尚未确认目标字段或缺少字段级写入规则")
        visited = set()

        def walk(node, trail):
            key = identity(node)
            if key in trail:
                issues.add("字段路径存在循环或依赖写入顺序，需补充核验")
                return
            if key in visited:
                return
            if len(trail) >= 64 or len(visited) >= 2000:
                issues.add("字段路径超出核验上限")
                return
            visited.add(key)
            nodes[key] = node
            if node.get("temporary"):
                issues.add("临时表生命周期尚未核验")
            if node.get("node_type") == "constant":
                leaves[key] = node
                return
            if not node.get("column_name") or node.get("column_name") == "*":
                issues.add("存在无法定位的字段或未展开星号")
            upstream = incoming.get(key, [])
            if not upstream:
                table = metadata.get(node.get("catalog_table_id"))
                if (not table or tuple(table.get(k) for k in ("database_name", "schema_name", "table_name")) != key[:3]
                        or node.get("unresolved") or not any(c["name"] == node.get("column_name") for c in table["columns"])):
                    issues.add("缺少上游字段元数据：" + ".".join(str(v or "未标注") for v in key))
                leaves[key] = node
                return
            if len({(r["script_version_id"], r["statement_id"]) for r in upstream}) > 1:
                issues.add("同一中间或目标字段存在多个写入语句，执行顺序和合并关系待确认")
            for rule in upstream:
                rules[rule["rule_id"]] = rule
                if not rule.get("statement_id") or not rule.get("source_line_start") or not rule.get("transformation_expression"):
                    issues.add("规则缺少语句位置或原始表达式")
                if rule.get("confidence_level") in {"low", "unknown"}:
                    issues.add("规则解析置信度不足")
                walk(rule["source"], trail | {key})

        if roots:
            walk(roots[0], set())
        paths.append({"field_id": field_id, "field_code": record["field"]["field_code"],
            "rule_ids": sorted(rules), "nodes": list(nodes.values()), "leaves": list(leaves.values()),
            "issues": sorted(issues), "technical_hash": technical_hash(record)})
    result = {"basis_hash": basis_hash(basis), "paths": paths}
    result["preview_hash"] = content_digest(result)
    return result


def path_issues(content):
    if not content.get("script_basis"):
        return []
    view = path_preview(content)
    records = {r["field"]["id"]: r for r in content["fields"]}
    issues = []
    for path in view["paths"]:
        record = records[path["field_id"]]
        saved = record.get("confirmed_path") or {}
        reasons = path["issues"][:]
        if (not confirmed_path(record) or saved.get("basis_hash") != view["basis_hash"]
                or saved.get("rule_ids") != path["rule_ids"]):
            reasons.append("当前脚本路径尚未人工确认或技术口径已变化")
        issues.extend({"code": f"{path['field_id']}:path:{i}", "field_id": path["field_id"], "message": reason}
            for i, reason in enumerate(reasons))
    return issues


def frozen_path_graph(content):
    """Use the existing table-field graph contract without querying live assets."""
    view = path_preview(content)
    basis = content["script_basis"]
    allowed = {rule_id for path in view["paths"] for rule_id in path["rule_ids"]}
    metadata = {t["id"]: t for t in basis["metadata"]}
    versions = {v["id"]: v for v in basis["versions"]}
    nodes, tables, edges, roots = {}, {}, [], []
    target_key = basis["confirmation"]["target_key"]
    bindings = basis["confirmation"]["field_bindings"]
    def add_node(node):
        field_id = bindings.get(node.get("column_name")) if node["table_key"] == target_key else None
        node_id = f"asset:target_field:{field_id}" if field_id else "script:" + content_digest(identity(node))[:24]
        # React Flow uses IDs inside selectors; raw JSON identities contain quotes.
        table_id = "script-table:" + content_digest(node["table_key"])[:24]
        meta = metadata.get(node.get("catalog_table_id"), {})
        assignment = meta.get("assignment") or {}
        table = tables.setdefault(table_id, {"id": table_id, "name": meta.get("table_comment") or node.get("table_name") or "常量",
            "technical_name": ".".join(str(node.get(k) or "未标注") for k in ("database_name", "schema_name", "table_name")),
            "layer": assignment.get("layer_name") or "未分类", "classification": assignment, "fields": []})
        if node_id not in nodes:
            column = next((c for c in meta.get("columns", []) if c["name"] == node.get("column_name")), {})
            nodes[node_id] = {"id": node_id, "table_key": table_id,
                "entity_type": "target_field" if field_id else "script_field", "canonical_entity_id": field_id,
                "unresolved_flag": bool(node.get("unresolved")), "data_type": column.get("data_type"),
                "display": {"business_name": column.get("comment") or node.get("column_name") or "常量",
                    "technical_name": node.get("column_name") or "常量"}}
            table["fields"].append(node_id)
        if field_id and node_id not in roots:
            roots.append(node_id)
        return node_id
    for rule in basis["rules"]:
        if rule["rule_id"] not in allowed:
            continue
        script = versions[rule["script_version_id"]]
        edges.append({**{k: rule.get(k) for k in ("edge_type", "transformation_expression", "join_condition",
            "filter_condition", "aggregation_rule", "code_mapping_rule")}, "id": rule["rule_id"],
            "source_node_id": add_node(rule["source"]), "target_node_id": add_node(rule["target"]),
            "relation_source": "fixed_script", "rules": {}, "evidence_refs": [{"source_name": script["path"],
                "version_no": script["version_no"], "quoted_content": f"行 {rule['source_line_start']} 至 {rule['source_line_end']}：{rule['transformation_expression']}"}]})
    return {"project_id": content["requirement"]["project_id"], "tables": list(tables.values()), "nodes": list(nodes.values()),
        "edges": edges, "root_ids": roots, "revision_id": None, "facts_mode": "requirement_fixed_scripts",
        "truncated": False, "omitted_frontier_count": 0, "limits": {"depth": 64, "max_nodes": 2000},
        "warnings": [issue["message"] for issue in path_issues(content)]}


def confirm_paths(db, requirement, payload, actor_id):
    from app.services.requirement_revisions import load_revision, append_revision
    previous = load_revision(db, requirement.project_id, requirement.id, payload.expected_content_version)
    if requirement.content_version != previous.content_version or previous.status != "draft":
        raise HTTPException(409, "只能在当前草稿核验路径")
    if not payload.rationale.strip():
        raise HTTPException(422, "请填写路径核验依据")
    content = deepcopy(previous.content_json)
    view = path_preview(content)
    if view["preview_hash"] != payload.preview_hash:
        raise HTTPException(409, "路径或技术内容已变化，请重新预览")
    if any(p["issues"] for p in view["paths"]):
        raise HTTPException(409, "路径存在未核验缺口，请补齐元数据或脚本后重新确认依据")
    from app.services.requirement_script_basis import script_basis_changes
    if script_basis_changes(db, requirement.project_id, content):
        raise HTTPException(409, "固定依据已变化，请先重新确认脚本依据")
    records = {r["field"]["id"]: r for r in content["fields"]}
    from app.services.requirement_gaps import field_gaps
    for path in view["paths"]:
        record = records[path["field_id"]]
        old_gaps = {g["id"] for g in field_gaps(record)}
        record["confirmed_path"] = {**path, "basis_hash": view["basis_hash"],
            "confirmed_by": actor_id, "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "rationale": payload.rationale.strip()}
        content["gaps"] = [g for g in content["gaps"] if g["id"] not in old_gaps
            and g["id"] != f"{path['field_id']}:edited_lineage"]
        content["gaps"].extend(field_gaps(record))
    content["assessment"] = "gaps" if content["gaps"] else "clear"
    return append_revision(db, requirement, content, previous.content_version, actor_id)
