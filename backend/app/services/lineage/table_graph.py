"""Bounded multi-root projection of existing lineage facts (no inferred edges)."""
from collections import deque
from sqlalchemy import select, or_
from app.models import TargetTable, TargetField, MartTable, MartField, SourceTable, SourceField, CatalogTable, CatalogColumn
from app.services.lineage.path_resolver import LineagePathResolver, LineagePathNotFound
from app.services.data_architecture import asset_classification_index

TABLES = {
    "target": (TargetTable, TargetField, "target_table_id", "target_field"),
    "mart": (MartTable, MartField, "mart_table_id", "mart_field"),
    "source": (SourceTable, SourceField, "source_table_id", "source_field"),
    "catalog": (CatalogTable, CatalogColumn, "catalog_table_id", "catalog_column"),
}


def bounded_paths(roots, edges, direction, depth, max_nodes):
    """Union of directed ancestor/descendant paths, not an undirected component."""
    outgoing, incoming = {}, {}
    for edge in edges:
        a, b = edge["source_node_id"], edge["target_node_id"]
        outgoing.setdefault(a, []).append(b)
        incoming.setdefault(b, []).append(a)
    traversals = ([incoming] if direction == "upstream" else
                  [outgoing] if direction == "downstream" else [incoming, outgoing])
    selected, omitted = set(roots), set()
    for adjacency in traversals:
        visited = set(roots)
        pending = deque((root, 0) for root in roots)
        while pending:
            current, level = pending.popleft()
            for neighbor in sorted(adjacency.get(current, [])):
                if neighbor in visited:
                    continue
                if level >= depth or (neighbor not in selected and len(selected) >= max_nodes):
                    omitted.add(neighbor)
                    continue
                selected.add(neighbor)
                visited.add(neighbor)
                pending.append((neighbor, level + 1))
    return selected, omitted - selected


def search_assets(db, project_id, query="", limit=60):
    result = []
    classifications = asset_classification_index(db, project_id)
    for kind, (table_model, field_model, parent_key, entity_type) in TABLES.items():
        statement = select(table_model).where(table_model.project_id == project_id)
        if query.strip():
            name = getattr(field_model, "field_name", None)
            code = getattr(field_model, "field_code", None)
            if name is None: name = field_model.column_name
            if code is None: code = field_model.column_name
            pattern = "%" + query.strip().replace("%", "\\%").replace("_", "\\_") + "%"
            matching = select(getattr(field_model, parent_key)).where(field_model.project_id == project_id,
                or_(name.ilike(pattern, escape="\\"), code.ilike(pattern, escape="\\")))
            table_name = table_model.table_name
            table_code = getattr(table_model, "table_code", table_name)
            statement = statement.where(or_(table_name.ilike(pattern, escape="\\"), table_code.ilike(pattern, escape="\\"), table_model.id.in_(matching)))
        for row in db.scalars(statement.order_by(table_model.id).limit(limit + 1)):
            result.append({"kind": kind, "id": row.id, "name": row.table_name,
                           "technical_name": getattr(row, "table_code", None) or row.table_name,
                           "physical_assignments": classifications.get((kind, row.id), [])})
    return {"items": result[:limit], "truncated": len(result) > limit}


def table_graph(db, project_id, kind, table_id, direction="both", depth=4, revision_id=None, max_nodes=500):
    if kind not in TABLES or direction not in {"upstream", "downstream", "both"} or not 1 <= depth <= 10:
        raise ValueError("无效查询范围")
    table_model, field_model, parent_key, entity_type = TABLES[kind]
    table = db.get(table_model, table_id)
    if table is None or table.project_id != project_id:
        raise LineagePathNotFound("所选表不存在或不可见")
    resolver = LineagePathResolver(db)
    revision = resolver._load_revision(project_id, revision_id)
    # Explicit history is script-only: never silently mix today's business mappings into an old version.
    if revision_id is None:
        resolver._add_business_mapping_graph(project_id, include_unresolved=True)
    if revision:
        resolver._add_revision_graph(project_id, revision, include_unresolved=True)
    roots = []
    fields = list(db.scalars(select(field_model).where(field_model.project_id == project_id,
        getattr(field_model, parent_key) == table_id).order_by(field_model.id).limit(max_nodes + 1)))
    truncated = len(fields) > max_nodes or resolver.truncated
    for field in fields[:max_nodes]:
        roots.append(resolver._add_asset(entity_type, field, project_id))
    selected, omitted_frontier = bounded_paths(roots, resolver.edges.values(), direction, depth, max_nodes)
    truncated = truncated or bool(omitted_frontier)
    nodes = [resolver.nodes[key] for key in sorted(selected)]
    edges = [edge for edge in resolver.edges.values() if edge["source_node_id"] in selected and edge["target_node_id"] in selected]
    tables = {}
    classifications = asset_classification_index(db, project_id)
    for node in nodes:
        descriptor = next(((k, spec) for k, spec in TABLES.items() if spec[3] == node["entity_type"]), None)
        parent = None
        if descriptor and node.get("canonical_entity_id"):
            k, (tm, fm, pk, _) = descriptor
            field = db.get(fm, node["canonical_entity_id"])
            if field and field.project_id == project_id:
                parent = db.get(tm, getattr(field, pk))
                if parent and parent.project_id != project_id: parent = None
        if parent:
            key = f"{k}:{parent.id}"
            name = parent.table_name
            technical = getattr(parent, "table_code", None) or name
            data_type = getattr(field, "field_type", None) or getattr(field, "data_type", None)
        else:
            # Unbound script nodes are separate, not merged by similar names.
            key = "unresolved:" + node["id"]
            name, technical, data_type = "未绑定资产", "归属待确认", None
        node["table_key"] = key
        node["data_type"] = data_type
        assignments = classifications.get((k, parent.id), []) if parent else []
        classification = assignments[0]["assignment"] if len(assignments) == 1 else None
        layer = (classification.get("layer_name") or "未分类") if classification is not None else node["layer_name"]
        tables.setdefault(key, {"id": key, "name": name, "technical_name": technical,
            "layer": layer, "classification": classification, "physical_assignments": assignments,
            "fields": [], "metadata_is_current": True})["fields"].append(node["id"])
    return {"project_id": project_id, "tables": list(tables.values()), "nodes": nodes, "edges": edges,
        "root_ids": roots, "revision_id": revision.id if revision else None, "direction": direction, "depth": depth,
        "truncated": truncated, "omitted_frontier_count": len(omitted_frontier),
        "facts_mode": "historical_scripts" if revision_id else "current_business_and_published_scripts",
        "warnings": resolver.warnings,
        "limits": {"max_nodes": max_nodes, "depth": depth}}
