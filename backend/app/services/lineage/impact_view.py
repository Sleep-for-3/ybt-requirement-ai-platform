"""Business-first, bounded projection of a persisted lineage impact.

``ImpactAnalysis`` remains the propagation fact.  This service turns its ID
sets into a reviewable view without copying the lineage graph or exposing raw
script/evidence content.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ImpactAnalysis,
    LineageEdge,
    LineageNode,
    LineageRevision,
    MappingEvidenceReference,
    MartToYbtMapping,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    ScriptChangeSet,
    ScriptFile,
    ScriptFileVersion,
    SourceToMartMapping,
)
from app.services.asset_display import AssetDisplayResolver
from app.services.lineage.path_resolver import LineagePathNotFound, LineagePathResolver
from app.services.security import redact_content


MAX_ASSETS_PER_TYPE = 500
MAX_MAPPINGS = 500
MAX_EVIDENCE = 2_000
MAX_EDGES = 1_000
MAX_REVISIONS = 200
MAX_PATH_TARGETS = 20
MAX_IMPACT_PATHS = 100


class ImpactDetailBuilder:
    def __init__(self, db: Session):
        self.db = db
        self.display = AssetDisplayResolver(db)
        self.warnings: list[str] = []
        self.truncated = False

    def build(
        self,
        impact: ImpactAnalysis,
        *,
        include_paths: bool = True,
        max_paths: int = 20,
    ) -> dict[str, Any]:
        max_paths = min(max(int(max_paths), 1), MAX_IMPACT_PATHS)
        project_id = int(impact.project_id)
        change_set = self.db.get(ScriptChangeSet, impact.change_set_id)
        if change_set is not None and change_set.project_id != project_id:
            change_set = None

        assets = {
            "source_fields": self._assets(
                "source_field", impact.affected_source_field_ids_json, project_id
            ),
            "mart_fields": self._assets(
                "mart_field", impact.affected_mart_field_ids_json, project_id
            ),
            "target_fields": self._assets(
                "target_field", impact.affected_target_field_ids_json, project_id
            ),
            "requirement_fields": self._assets(
                "target_field", impact.affected_requirement_ids_json, project_id
            ),
        }
        mapping_refs = _parse_mapping_refs(impact.affected_mapping_ids_json or [])
        mappings, mapping_evidence = self._mapping_details(project_id, mapping_refs)
        affected_edges = self._edge_details(
            project_id, impact.affected_lineage_edge_ids_json or []
        )
        script_context = self._script_context(project_id, change_set)
        revisions = self._revision_context(project_id, change_set)
        target_ids = _unique_ints([
            *(impact.affected_target_field_ids_json or []),
            *(impact.affected_requirement_ids_json or []),
        ])
        paths = self._impact_paths(
            project_id,
            target_ids,
            revisions,
            max_paths=max_paths,
        ) if include_paths else []

        evidence = _unique_dicts([
            *mapping_evidence,
            *(
                item
                for edge in affected_edges
                for item in edge.get("evidence_refs", [])
            ),
            *(
                item
                for path_group in paths
                for version in path_group.get("versions", [])
                for item in version.get("path", {}).get("evidence_refs", [])
            ),
        ])
        return {
            "assets": assets,
            "mappings": mappings,
            "affected_edges": affected_edges,
            "script": script_context,
            "lineage_versions": revisions,
            "paths": paths,
            "evidence_refs": evidence[:MAX_EVIDENCE],
            "confidence": _impact_confidence(impact, paths),
            "pending_confirmation": bool(impact.open_questions_json),
            "truncated": self.truncated or len(evidence) > MAX_EVIDENCE,
            "warnings": list(dict.fromkeys(self.warnings)),
        }

    def _assets(
        self,
        entity_type: str,
        raw_ids: Iterable[Any] | None,
        project_id: int,
    ) -> list[dict[str, Any]]:
        ids = _unique_ints(raw_ids or [])
        if len(ids) > MAX_ASSETS_PER_TYPE:
            ids = ids[:MAX_ASSETS_PER_TYPE]
            self.truncated = True
            self.warnings.append("受影响资产过多，详情仅返回前 500 项")
        return self.display.resolve_many(
            ((entity_type, item) for item in ids), project_id=project_id
        )

    def _mapping_details(
        self,
        project_id: int,
        refs: list[tuple[str, int]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if len(refs) > MAX_MAPPINGS:
            refs = refs[:MAX_MAPPINGS]
            self.truncated = True
            self.warnings.append("受影响映射过多，详情仅返回前 500 项")
        ids_by_type: dict[str, list[int]] = defaultdict(list)
        for mapping_type, mapping_id in refs:
            ids_by_type[mapping_type].append(mapping_id)
        evidence_rows = list(self.db.scalars(select(MappingEvidenceReference).where(
            MappingEvidenceReference.project_id == project_id,
            _mapping_reference_condition(ids_by_type),
        ).order_by(MappingEvidenceReference.id).limit(MAX_EVIDENCE + 1)).all()) if refs else []
        if len(evidence_rows) > MAX_EVIDENCE:
            evidence_rows = evidence_rows[:MAX_EVIDENCE]
            self.truncated = True
            self.warnings.append("映射证据过多，详情仅返回前 2000 项")
        evidence_by_mapping: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for item in evidence_rows:
            evidence_by_mapping[(item.mapping_type, item.mapping_id)].append(
                _evidence_dict(item)
            )

        rows: dict[tuple[str, int], Any] = {}
        model_by_type = {
            "source_to_mart": SourceToMartMapping,
            "mart_to_ybt": MartToYbtMapping,
            "scenario_business": ScenarioBusinessMapping,
            "scenario_technical": ScenarioTechnicalLineage,
        }
        for mapping_type, ids in ids_by_type.items():
            model = model_by_type.get(mapping_type)
            if model is None:
                continue
            for row in self.db.scalars(select(model).where(
                model.project_id == project_id,
                model.id.in_(ids),
            )).all():
                rows[(mapping_type, row.id)] = row

        result = []
        for mapping_type, mapping_id in refs:
            row = rows.get((mapping_type, mapping_id))
            evidence = evidence_by_mapping.get((mapping_type, mapping_id), [])
            if row is None:
                result.append({
                    "mapping_type": mapping_type,
                    "mapping_id": mapping_id,
                    "display_name": "映射已删除或不可见",
                    "technical_identifier": f"{mapping_type}:{mapping_id}",
                    "status": "missing",
                    "lineage_status": "unknown",
                    "confidence_level": "low",
                    "source_assets": [],
                    "target_assets": [],
                    "rules": {},
                    "evidence_refs": evidence,
                })
                continue
            result.append(self._mapping_dict(mapping_type, row, evidence, project_id))
        return result, [item for values in evidence_by_mapping.values() for item in values]

    def _mapping_dict(
        self,
        mapping_type: str,
        row: Any,
        evidence: list[dict[str, Any]],
        project_id: int,
    ) -> dict[str, Any]:
        source_assets: list[dict[str, Any]] = []
        target_assets: list[dict[str, Any]] = []
        if mapping_type == "source_to_mart":
            source_assets = self._evidence_assets(evidence, project_id)
            target = self.display.resolve("mart_field", row.mart_field_id, project_id=project_id)
            target_assets = [target] if target else []
            status = row.mapping_status
            display_name = row.mapping_name or (
                f"{target['display_name']}来源映射" if target else f"来源到集市映射 #{row.id}"
            )
            rules = _rules(row, (
                "business_rule", "join_condition", "filter_condition", "priority_rule",
                "merge_rule", "code_mapping_rule", "null_handling_rule",
                "exception_rule", "quality_check_rule",
            ))
        elif mapping_type == "mart_to_ybt":
            source = self.display.resolve("mart_field", row.mart_field_id, project_id=project_id) if row.mart_field_id else None
            target = self.display.resolve("target_field", row.target_field_id, project_id=project_id)
            source_assets = [source] if source else []
            target_assets = [target] if target else []
            status = row.mapping_status
            display_name = row.mapping_name or (
                f"{target['display_name']}报送映射" if target else f"集市到监管映射 #{row.id}"
            )
            rules = _rules(row, (
                "business_rule", "join_condition", "filter_condition", "code_mapping_rule",
                "null_handling_rule", "reporting_condition", "validation_rule",
            ))
        elif mapping_type == "scenario_business":
            target = self.display.resolve("target_field", row.target_field_id, project_id=project_id)
            target_assets = [target] if target else []
            status = row.business_confirm_status
            display_name = f"{target['display_name']}业务口径" if target else f"场景业务映射 #{row.id}"
            rules = _rules(row, ("business_definition", "remarks", "open_questions"))
        else:
            target = self.display.resolve("target_field", row.target_field_id, project_id=project_id)
            target_assets = [target] if target else []
            status = row.tech_confirm_status
            display_name = f"{target['display_name']}技术溯源" if target else f"场景技术溯源 #{row.id}"
            rules = _rules(row, ("processing_logic", "remarks", "open_questions"))
            source_assets = [{
                "entity_type": "described_source",
                "display_name": _text(row.source_field_chinese_name) or _text(row.source_table_chinese_name) or "缺少业务备注",
                "technical_name": _text(row.source_field_english_name) or _text(row.source_table_english_name),
                "technical_identifier": ".".join(filter(None, [
                    _text(row.source_database_name),
                    _text(row.source_schema_name),
                    _text(row.source_table_english_name),
                    _text(row.source_field_english_name),
                ])) or None,
                "system_name": _text(row.source_system_name),
            }]
        return {
            "mapping_type": mapping_type,
            "mapping_id": row.id,
            "display_name": display_name,
            "technical_identifier": f"{mapping_type}:{row.id}",
            "status": status,
            "lineage_status": getattr(row, "lineage_status", None),
            "confidence_level": getattr(row, "confidence_level", "medium"),
            "source_assets": source_assets,
            "target_assets": target_assets,
            "rules": rules,
            "evidence_refs": evidence,
        }

    def _evidence_assets(
        self,
        evidence: list[dict[str, Any]],
        project_id: int,
    ) -> list[dict[str, Any]]:
        result = []
        for item in evidence:
            entity_type = item.get("evidence_type")
            if entity_type not in {"source_field", "catalog_column", "mart_field", "target_field"}:
                continue
            entity_id = item.get("evidence_id")
            if entity_id is None:
                continue
            display = self.display.resolve(entity_type, int(entity_id), project_id=project_id)
            if display is not None:
                result.append(display)
        return _unique_dicts(result)

    def _edge_details(self, project_id: int, raw_ids: Iterable[Any]) -> list[dict[str, Any]]:
        ids = _unique_ints(raw_ids)
        if len(ids) > MAX_EDGES:
            ids = ids[:MAX_EDGES]
            self.truncated = True
            self.warnings.append("受影响血缘边过多，详情仅返回前 1000 项")
        edges = list(self.db.scalars(select(LineageEdge).where(
            LineageEdge.project_id == project_id,
            LineageEdge.id.in_(ids),
        ).order_by(LineageEdge.id)).all()) if ids else []
        node_ids = {item.source_node_id for item in edges} | {item.target_node_id for item in edges}
        nodes = {
            item.id: item
            for item in self.db.scalars(select(LineageNode).where(
                LineageNode.project_id == project_id,
                LineageNode.id.in_(node_ids),
            )).all()
        } if node_ids else {}
        result = []
        for edge in edges:
            source = nodes.get(edge.source_node_id)
            target = nodes.get(edge.target_node_id)
            result.append({
                "id": edge.id,
                "source": self.display.describe_lineage_node(source) if source else None,
                "target": self.display.describe_lineage_node(target) if target else None,
                "edge_type": edge.edge_type,
                "transformation_type": edge.transformation_type,
                "transformation_expression": _text(edge.transformation_expression, 1_000),
                "join_condition": _text(edge.join_condition, 1_000),
                "filter_condition": _text(edge.filter_condition, 1_000),
                "aggregation_rule": _text(edge.aggregation_rule, 1_000),
                "code_mapping_rule": _text(edge.code_mapping_rule, 1_000),
                "source_line_start": edge.source_line_start,
                "source_line_end": edge.source_line_end,
                "confidence_level": edge.confidence_level,
                "evidence_refs": [{
                    "type": "lineage_edge",
                    "id": edge.id,
                    "script_file_version_id": edge.script_file_version_id,
                    "statement_id": edge.statement_id,
                    "source_line_start": edge.source_line_start,
                    "source_line_end": edge.source_line_end,
                    "summary": _safe_json_summary(edge.evidence_json),
                }],
            })
        return result

    def _script_context(
        self,
        project_id: int,
        change_set: ScriptChangeSet | None,
    ) -> dict[str, Any] | None:
        if change_set is None:
            return None
        script = self.db.get(ScriptFile, change_set.script_file_id)
        if script is None or script.project_id != project_id:
            return None
        versions = []
        for role, version_id in (
            ("before", change_set.from_version_id),
            ("after", change_set.to_version_id),
        ):
            version = self.db.get(ScriptFileVersion, version_id) if version_id else None
            if version is None or version.project_id != project_id or version.script_file_id != script.id:
                continue
            versions.append({
                "role": role,
                "id": version.id,
                "version_no": version.version_no,
                "git_commit_sha": version.git_commit_sha,
                "parse_status": version.parse_status,
                "dialect": version.dialect,
                "warnings": [_text(item, 500) for item in (version.warnings_json or [])],
                "created_at": version.created_at,
            })
        return {
            "id": script.id,
            "display_name": script.logical_target_name or script.file_name,
            "technical_name": script.relative_path,
            "relative_path": script.relative_path,
            "file_type": script.file_type,
            "enabled": script.enabled,
            "change_type": change_set.change_type,
            "change_status": change_set.status,
            "versions": versions,
        }

    def _revision_context(
        self,
        project_id: int,
        change_set: ScriptChangeSet | None,
    ) -> dict[str, Any]:
        rows = list(self.db.scalars(select(LineageRevision).where(
            LineageRevision.project_id == project_id,
        ).order_by(LineageRevision.revision_no.desc()).limit(MAX_REVISIONS)).all())
        current = next((item for item in rows if item.status == "published"), None)
        before_id = change_set.from_version_id if change_set else None
        after_id = change_set.to_version_id if change_set else None
        baseline = next((item for item in rows if _revision_contains(item, before_id)), None)
        candidate = next((item for item in rows if _revision_contains(item, after_id)), None)
        return {
            "current_published": _revision_dict(current),
            "baseline": _revision_dict(baseline),
            "candidate": _revision_dict(candidate),
            "comparison_available": bool(
                baseline is not None and candidate is not None and baseline.id != candidate.id
            ),
        }

    def _impact_paths(
        self,
        project_id: int,
        target_ids: list[int],
        revisions: dict[str, Any],
        *,
        max_paths: int,
    ) -> list[dict[str, Any]]:
        if len(target_ids) > MAX_PATH_TARGETS:
            target_ids = target_ids[:MAX_PATH_TARGETS]
            self.truncated = True
            self.warnings.append("受影响监管字段过多，路径仅返回前 20 个字段")
        revision_slots = []
        for role in ("baseline", "candidate", "current_published"):
            revision = revisions.get(role)
            if revision and revision.get("id") and revision["id"] not in {
                item[1] for item in revision_slots
            }:
                revision_slots.append((role, int(revision["id"])))
        per_query = max(1, max_paths // max(len(target_ids) * max(len(revision_slots), 1), 1))
        result = []
        for target_id in target_ids:
            display = self.display.resolve("target_field", target_id, project_id=project_id)
            versions = []
            for role, revision_id in revision_slots:
                try:
                    path = LineagePathResolver(self.db).resolve(
                        project_id,
                        root_entity_type="target_field",
                        root_entity_id=target_id,
                        direction="upstream",
                        depth=10,
                        lineage_revision_id=revision_id,
                        include_unresolved=True,
                        view="business",
                        max_paths=per_query,
                    )
                except LineagePathNotFound:
                    continue
                versions.append({"role": role, "revision_id": revision_id, "path": path})
            result.append({
                "target_field_id": target_id,
                "display": display,
                "versions": versions,
            })
        return result


def _parse_mapping_refs(values: Iterable[Any]) -> list[tuple[str, int]]:
    aliases = {
        "source_to_mart_mapping": "source_to_mart",
        "mart_to_ybt_mapping": "mart_to_ybt",
        "scenario_business_mapping": "scenario_business",
        "scenario_technical_lineage": "scenario_technical",
    }
    supported = {"source_to_mart", "mart_to_ybt", "scenario_business", "scenario_technical"}
    result = []
    seen = set()
    for value in values:
        mapping_type, separator, raw_id = str(value).partition(":")
        mapping_type = aliases.get(mapping_type, mapping_type)
        if not separator or mapping_type not in supported:
            continue
        try:
            key = (mapping_type, int(raw_id))
        except (TypeError, ValueError):
            continue
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _mapping_reference_condition(ids_by_type: dict[str, list[int]]):
    conditions = []
    for mapping_type, ids in ids_by_type.items():
        conditions.append(
            (MappingEvidenceReference.mapping_type == mapping_type)
            & (MappingEvidenceReference.mapping_id.in_(ids))
        )
    condition = conditions[0]
    for item in conditions[1:]:
        condition = condition | item
    return condition


def _evidence_dict(row: MappingEvidenceReference) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": "mapping_evidence",
        "mapping_type": row.mapping_type,
        "mapping_id": row.mapping_id,
        "evidence_type": row.evidence_type,
        "evidence_id": row.evidence_id,
        "source_name": _text(row.source_name, 255),
        "location": _text(row.location_text, 255),
        "summary": _text(row.evidence_summary, 1_000),
    }


def _rules(row: Any, names: Iterable[str]) -> dict[str, str]:
    return {
        name: value
        for name in names
        if (value := _text(getattr(row, name, None), 1_000)) is not None
    }


def _revision_contains(revision: LineageRevision, version_id: int | None) -> bool:
    if version_id is None:
        return False
    return any(
        int(item.get("version_id", -1)) == int(version_id)
        for item in (revision.source_manifest_json or [])
        if isinstance(item, dict)
    )


def _revision_dict(row: LineageRevision | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "revision_no": row.revision_no,
        "status": row.status,
        "trigger_type": row.trigger_type,
        "source_commit_sha": row.source_commit_sha,
        "node_count": row.node_count,
        "edge_count": row.edge_count,
        "warnings": row.warnings_json or [],
        "created_at": row.created_at,
        "published_at": row.published_at,
    }


def _impact_confidence(impact: ImpactAnalysis, paths: list[dict[str, Any]]) -> str:
    confidences = [
        version.get("path", {}).get("confidence", "low")
        for group in paths
        for version in group.get("versions", [])
    ]
    if not confidences:
        return "low" if impact.open_questions_json else "medium"
    rank = {"low": 0, "medium": 1, "high": 2}
    return min(confidences, key=lambda item: rank.get(str(item), 0))


def _unique_ints(values: Iterable[Any]) -> list[int]:
    result = []
    seen = set()
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _unique_dicts(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for value in values:
        key = tuple(sorted((str(name), str(item)) for name, item in value.items()))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _safe_json_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = ("statement_index", "parser", "clause", "operation", "expression_type")
    result: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if item is None:
            continue
        # Numeric/boolean evidence coordinates keep their type so clients can
        # use them for navigation; free text is still length-bounded/redacted.
        result[key] = item if isinstance(item, (int, float, bool)) else _text(item, 500)
    return result


def _text(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return redact_content(result[:limit]) if result else None


__all__ = ["ImpactDetailBuilder"]
