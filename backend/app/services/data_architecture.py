"""Versioned bank/project architecture; no table-name inference on reads."""
from copy import deepcopy
import re

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import BusinessSystem, CatalogTable, CatalogImportBinding, TargetTable, TemplateVersion
from app.models.data_architecture import CatalogClassification, DataArchitecture, DataArchitectureRevision


def examples():
    def chain(names):
        layers = [{"key": f"layer_{i}", "name": name, "active": True} for i, name in enumerate(names)]
        return {"layers": layers, "relations": [{"from": a["key"], "to": b["key"]} for a, b in zip(layers, layers[1:])]}
    return [chain(["业务系统", "贴源层", "一表通报送表"]),
            chain(["业务系统", "ODS", "DWD", "DWS", "监管集市", "一表通报送表"])]


def validate_definition(value):
    value = deepcopy(value)
    layers, relations = value.get("layers"), value.get("relations", [])
    if not isinstance(layers, list) or not 1 <= len(layers) <= 100 or not isinstance(relations, list):
        raise HTTPException(422, "请配置 1 至 100 个层级")
    keys = set()
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("key"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", layer["key"]):
            raise HTTPException(422, "层级需要稳定标识")
        if layer["key"] in keys or not isinstance(layer.get("name"), str) or not layer["name"].strip() or len(layer["name"]) > 100:
            raise HTTPException(422, "层级标识重复或名称无效")
        if not isinstance(layer.get("active", True), bool):
            raise HTTPException(422, "层级启用状态无效")
        layer.setdefault("active", True)
        keys.add(layer["key"])
    for relation in relations:
        if not isinstance(relation, dict) or relation.get("from") not in keys or relation.get("to") not in keys or relation["from"] == relation["to"]:
            raise HTTPException(422, "关系必须引用不同的已配置层级")
    return {"layers": layers, "relations": relations}


def get_architecture(db, *, project_id=None, institution_id=None):
    if (project_id is None) == (institution_id is None):
        raise HTTPException(422, "架构只能属于一个机构或项目")
    return db.scalar(select(DataArchitecture).where(
        DataArchitecture.project_id == project_id, DataArchitecture.institution_id == institution_id))


def save_architecture(db, definition, expected_version, *, project_id=None, institution_id=None):
    definition = validate_definition(definition)
    row = get_architecture(db, project_id=project_id, institution_id=institution_id)
    if (row.version if row else 0) != expected_version:
        raise HTTPException(409, "架构已变化，请刷新后重试")
    if row:
        # Never remove stable identifiers: disabled layers preserve assignments and snapshots.
        keys = {layer["key"] for layer in definition["layers"]}
        for old in row.definition_json["layers"]:
            if old["key"] not in keys:
                definition["layers"].append({**old, "active": False})
        result = db.execute(update(DataArchitecture).where(DataArchitecture.id == row.id,
            DataArchitecture.version == expected_version).values(version=expected_version + 1, definition_json=definition))
        if result.rowcount != 1:
            raise HTTPException(409, "架构已变化，请刷新后重试")
        db.refresh(row)
    else:
        row = DataArchitecture(project_id=project_id, institution_id=institution_id, definition_json=definition, version=1)
        db.add(row)
        db.flush()
    db.add(DataArchitectureRevision(architecture_id=row.id, version=row.version, definition_json=deepcopy(definition)))
    db.flush()
    return row


def copy_institution_template(db, project, expected_version=0):
    if project.institution_id is None:
        raise HTTPException(409, "项目尚未关联机构")
    template = get_architecture(db, institution_id=project.institution_id)
    if template is None:
        raise HTTPException(404, "机构尚未配置架构模板")
    if get_architecture(db, project_id=project.id):
        raise HTTPException(409, "项目已有独立架构，请在项目中编辑")
    return save_architecture(db, deepcopy(template.definition_json), expected_version, project_id=project.id)


def assign_table(db, project_id, table_id, assignment, architecture_version):
    table = db.get(CatalogTable, table_id)
    if table is None or table.project_id != project_id:
        raise HTTPException(404, "Resource not found")
    architecture = get_architecture(db, project_id=project_id)
    if architecture is None or architecture.version != architecture_version:
        raise HTTPException(409, "请先刷新项目架构")
    layer_key = assignment.get("layer_key")
    layer = next((x for x in architecture.definition_json["layers"] if x["key"] == layer_key and x["active"]), None)
    if layer_key is not None and layer is None:
        raise HTTPException(422, "层级不存在或已停用")
    normalized = {"layer_key": layer_key, "layer_name": layer["name"] if layer else None}
    for key, model in (("business_system_id", BusinessSystem), ("target_table_id", TargetTable), ("template_version_id", TemplateVersion)):
        identity = assignment.get(key)
        if identity is not None:
            resource = db.get(model, identity)
            if resource is None or resource.project_id != project_id:
                raise HTTPException(404, "Resource not found")
        normalized[key] = identity
    if normalized["business_system_id"]:
        normalized["business_system_name"] = db.get(BusinessSystem, normalized["business_system_id"]).system_name
    if bool(normalized["target_table_id"]) != bool(normalized["template_version_id"]):
        raise HTTPException(422, "监管关联需要同时确认目标表和模板版本")
    if normalized["target_table_id"]:
        target = db.get(TargetTable, normalized["target_table_id"])
        template = db.get(TemplateVersion, normalized["template_version_id"])
        if not any(str(sheet.get("table_code") or sheet.get("sheet_name")) == target.table_code
                   for sheet in template.parsed_snapshot_json or []):
            raise HTTPException(422, "目标监管表不在所选模板版本中")
        normalized.update(target_table_code=target.table_code, target_table_name=target.table_name,
            template_code=template.template_code, template_version_no=template.version_no)
    revision = db.scalar(select(DataArchitectureRevision).where(DataArchitectureRevision.architecture_id == architecture.id,
        DataArchitectureRevision.version == architecture.version))
    row = db.scalar(select(CatalogClassification).where(CatalogClassification.catalog_table_id == table_id))
    if row is None:
        row = CatalogClassification(project_id=project_id, catalog_table_id=table_id)
        db.add(row)
    row.assignment_json = normalized
    row.architecture_revision_id = revision.id
    db.flush()
    return row


def current_assignment(binding, architecture):
    """Project current labels without rewriting confirmed assignments or frozen content."""
    assignment = deepcopy(binding.assignment_json) if binding else {"layer_key": None}
    if architecture and assignment.get("layer_key"):
        layer = next((entry for entry in architecture.definition_json["layers"]
            if entry["key"] == assignment["layer_key"]), None)
        if layer:
            assignment["layer_name"] = layer["name"]
            if not layer["active"]:
                assignment["layer_active"] = False
    return assignment


def table_classifications(db, project_id):
    architecture = get_architecture(db, project_id=project_id)
    rows = db.execute(select(CatalogTable, CatalogClassification).outerjoin(CatalogClassification,
        CatalogClassification.catalog_table_id == CatalogTable.id).where(CatalogTable.project_id == project_id)
        .order_by(CatalogTable.id)).all()
    return [{"catalog_table_id": table.id, "datasource_id": table.datasource_id, "database_name": table.database_name,
        "schema_name": table.schema_name, "table_name": table.table_name,
        "assignment": current_assignment(binding, architecture),
        "architecture_revision_id": binding.architecture_revision_id if binding else None} for table, binding in rows]


def classification_options(db, project_id):
    systems = list(db.scalars(select(BusinessSystem).where(BusinessSystem.project_id == project_id)
        .order_by(BusinessSystem.system_code)))
    targets = list(db.scalars(select(TargetTable).where(TargetTable.project_id == project_id)
        .order_by(TargetTable.table_code)))
    templates = list(db.scalars(select(TemplateVersion).where(TemplateVersion.project_id == project_id)
        .order_by(TemplateVersion.id.desc())))
    return {"business_systems": [{"id": s.id, "name": s.system_name, "code": s.system_code,
                "enabled": s.enabled} for s in systems],
        "targets": [{"id": t.id, "code": t.table_code, "name": t.table_name} for t in targets],
        "templates": [{"id": t.id, "code": t.template_code, "version_no": t.version_no,
            "status": t.status, "target_ids": [target.id for target in targets if any(
                str(sheet.get("table_code") or sheet.get("sheet_name")) == target.table_code
                for sheet in t.parsed_snapshot_json or [])]} for t in templates]}


def asset_classification_index(db, project_id):
    """Resolve only explicit catalog bindings, never names or layer-shaped prefixes."""
    physical = {row["catalog_table_id"]: row for row in table_classifications(db, project_id)}
    result = {("catalog", identity): [row] for identity, row in physical.items()}
    for binding in db.scalars(select(CatalogImportBinding).where(CatalogImportBinding.project_id == project_id)):
        row = physical.get(binding.catalog_table_id)
        if row is None:
            continue
        for kind in ("source", "mart"):
            identity = getattr(binding, f"{kind}_table_id")
            if identity:
                entries = result.setdefault((kind, identity), [])
                if not any(item["catalog_table_id"] == row["catalog_table_id"] for item in entries):
                    entries.append(row)
    for row in physical.values():
        target = row["assignment"].get("target_table_id")
        if target:
            result.setdefault(("target", target), []).append(row)
    return result


def suggest_classifications(db, project_id, rules):
    """Preview only. Conflicting rules remain alternatives for human selection."""
    architecture = get_architecture(db, project_id=project_id)
    active = {x["key"] for x in architecture.definition_json["layers"] if x["active"]} if architecture else set()
    for rule in rules:
        if rule.get("layer_key") not in active or not any(rule.get(key) for key in ("database_name", "schema_name", "table_prefix")):
            raise HTTPException(422, "分类建议需要有效层级及至少一个匹配条件")
    suggestions = []
    for table in table_classifications(db, project_id):
        if table["assignment"].get("layer_key") is not None:
            continue
        matches = [rule for rule in rules if all(not rule.get(key) or table[key] == rule[key]
            for key in ("database_name", "schema_name")) and
            (not rule.get("table_prefix") or table["table_name"].startswith(rule["table_prefix"]))]
        if matches:
            suggestions.append({**table, "suggested_layer_keys": sorted({rule["layer_key"] for rule in matches}),
                                "requires_confirmation": True})
    return suggestions
