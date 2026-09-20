"""Version-aware, end-to-end business and technical lineage paths.

The resolver is a read-only projection. It joins the existing approved
SourceToMart/MartToYbt mappings with one immutable LineageRevision; it never
creates a second lineage fact store and never promotes AI suggestions.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn,
    CatalogImportBinding,
    LineageNode,
    LineageRevision,
    LineageRevisionEdge,
    LineageRevisionNode,
    MappingEvidenceReference,
    MartField,
    MartToYbtMapping,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    SourceToMartMapping,
    TargetField,
)
from app.services.asset_display import AssetDisplayResolver, LAYER_NAMES
from app.services.security import redact_content
from app.services.lineage.view_projection import project_nodes, validate_view


ROOT_MODELS: dict[str, type[Any]] = {
    "target_field": TargetField,
    "mart_field": MartField,
    "source_field": SourceField,
    "catalog_column": CatalogColumn,
    "lineage_node": LineageNode,
}
APPROVED_MAPPING_STATUS = "approved"
MAX_REVISION_NODES = 5_000
MAX_REVISION_EDGES = 10_000
MAX_MAPPING_ROWS = 5_000
MAX_PATHS = 200
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


class LineagePathNotFound(ValueError):
    """Raised when a project-scoped root or revision is not visible."""


class LineagePathResolver:
    def __init__(self, db: Session):
        self.db = db
        self.display = AssetDisplayResolver(db)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.gaps: list[dict[str, Any]] = []
        self.truncated = False
        self._asset_cache: dict[tuple[str, int], str | None] = {}

    def resolve(
        self,
        project_id: int,
        *,
        root_entity_type: str,
        root_entity_id: int,
        direction: str = "upstream",
        depth: int = 10,
        lineage_revision_id: int | None = None,
        include_unresolved: bool = True,
        view: str = "business",
        max_paths: int = 100,
    ) -> dict[str, Any]:
        if root_entity_type not in ROOT_MODELS:
            raise ValueError("Unsupported lineage root type")
        if direction not in {"upstream", "downstream", "both"}:
            raise ValueError("Invalid lineage direction")
        if not 1 <= int(depth) <= 10:
            raise ValueError("Lineage depth must be between 1 and 10")
        view = validate_view(view)
        max_paths = min(max(int(max_paths), 1), MAX_PATHS)

        root = self._load_root(project_id, root_entity_type, root_entity_id)
        revision = self._load_revision(project_id, lineage_revision_id)

        self._add_business_mapping_graph(project_id, include_unresolved=include_unresolved)
        lineage_node_keys = self._add_revision_graph(
            project_id,
            revision,
            include_unresolved=include_unresolved,
        ) if revision is not None else {}

        if root_entity_type == "lineage_node":
            root_node_id = lineage_node_keys.get(int(root.id))
            if root_node_id is None:
                root_node_id = self._add_live_lineage_node(root, include_unresolved=include_unresolved)
        else:
            root_node_id = self._add_asset(root_entity_type, root, project_id)
        if root_node_id is None or root_node_id not in self.nodes:
            raise LineagePathNotFound("Lineage root is not present in the selected revision")

        paths, selected_node_ids, selected_edge_ids, traversal_truncated = self._walk_paths(
            root_node_id,
            direction=direction,
            depth=depth,
            max_paths=max_paths,
        )
        self.truncated = self.truncated or traversal_truncated
        selected_nodes = [self.nodes[node_id] for node_id in selected_node_ids]
        selected_edges = [self.edges[edge_id] for edge_id in selected_edge_ids]
        self._add_result_gaps(
            root_node_id,
            paths,
            selected_nodes,
            selected_edges,
            direction=direction,
            revision=revision,
        )
        if self.truncated:
            self.warnings.append("结果已达到查询预算，请缩小方向、层级或根节点范围")

        # Apply the presentation contract only after gap detection so
        # ``missing_business_comment`` keeps its business-label meaning.  The
        # root node is always part of ``selected_nodes``, so one projection
        # pass covers every node returned in the response.
        project_nodes(selected_nodes, view)
        unresolved_nodes = [item for item in selected_nodes if item["unresolved_flag"]]
        evidence_refs = _unique_dicts(
            evidence
            for edge in selected_edges
            for evidence in edge.get("evidence_refs", [])
        )
        confidence = _overall_confidence(paths, unresolved_nodes, self.warnings)
        root_display = self.nodes[root_node_id]["display"]
        return {
            "project_id": int(project_id),
            "root": {
                "entity_type": root_entity_type,
                "entity_id": int(root_entity_id),
                "node_id": root_node_id,
                "display": root_display,
            },
            "revision_id": revision.id if revision is not None else None,
            "revision_no": revision.revision_no if revision is not None else None,
            "as_of": (
                revision.published_at or revision.created_at
                if revision is not None
                else None
            ),
            "direction": direction,
            "depth": int(depth),
            "view": view,
            "nodes": selected_nodes,
            "edges": selected_edges,
            "paths": paths,
            "unresolved_nodes": unresolved_nodes,
            "gap_recommendations": _dedupe_gaps(self.gaps),
            "truncated": self.truncated,
            "warnings": list(dict.fromkeys(self.warnings)),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        }

    def _load_root(self, project_id: int, entity_type: str, entity_id: int) -> Any:
        model = ROOT_MODELS[entity_type]
        entity = self.db.get(model, int(entity_id))
        if entity is None or int(getattr(entity, "project_id", -1)) != int(project_id):
            raise LineagePathNotFound("Lineage root not found")
        return entity

    def _load_revision(self, project_id: int, revision_id: int | None) -> LineageRevision | None:
        if revision_id is not None:
            revision = self.db.get(LineageRevision, int(revision_id))
            if revision is None or revision.project_id != int(project_id):
                raise LineagePathNotFound("Lineage revision not found")
            return revision
        revision = self.db.scalar(select(LineageRevision).where(
            LineageRevision.project_id == int(project_id),
            LineageRevision.status == "published",
        ).order_by(LineageRevision.revision_no.desc()).limit(1))
        if revision is None:
            self.warnings.append("项目尚无已发布血缘版本；当前仅返回已审核业务映射")
        else:
            self.warnings.append("未指定版本，已使用最近发布的正式血缘版本")
        return revision

    def _add_business_mapping_graph(self, project_id: int, *, include_unresolved: bool) -> None:
        mart_rows = list(self.db.scalars(select(MartToYbtMapping).where(
            MartToYbtMapping.project_id == project_id,
            MartToYbtMapping.mapping_status == APPROVED_MAPPING_STATUS,
        ).order_by(MartToYbtMapping.id).limit(MAX_MAPPING_ROWS + 1)).all())
        source_rows = list(self.db.scalars(select(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project_id,
            SourceToMartMapping.mapping_status == APPROVED_MAPPING_STATUS,
        ).order_by(SourceToMartMapping.id).limit(MAX_MAPPING_ROWS + 1)).all())
        if len(mart_rows) > MAX_MAPPING_ROWS or len(source_rows) > MAX_MAPPING_ROWS:
            self.truncated = True
            mart_rows = mart_rows[:MAX_MAPPING_ROWS]
            source_rows = source_rows[:MAX_MAPPING_ROWS]

        pairs = [
            *(('mart_to_ybt', int(row.id)) for row in mart_rows),
            *(('source_to_mart', int(row.id)) for row in source_rows),
        ]
        evidence_by_pair = self._mapping_evidence(project_id, pairs)
        catalog_ids = {
            int(item.evidence_id)
            for values in evidence_by_pair.values()
            for item in values
            if item.evidence_type == "catalog_column" and item.evidence_id is not None
        }
        bindings_by_column: dict[int, list[CatalogImportBinding]] = defaultdict(list)
        if catalog_ids:
            for binding in self.db.scalars(select(CatalogImportBinding).where(
                CatalogImportBinding.project_id == project_id,
                CatalogImportBinding.catalog_column_id.in_(catalog_ids),
            ).order_by(CatalogImportBinding.id)).all():
                if binding.catalog_column_id is not None:
                    bindings_by_column[int(binding.catalog_column_id)].append(binding)

        for mapping in mart_rows:
            target_id = self._add_asset_by_id("target_field", mapping.target_field_id, project_id)
            mart_id = self._add_asset_by_id("mart_field", mapping.mart_field_id, project_id) if mapping.mart_field_id else None
            evidence = _evidence_payload(evidence_by_pair.get(("mart_to_ybt", mapping.id), []))
            if target_id is None:
                self._broken_mapping_gap("mart_to_ybt", mapping.id, "目标字段不存在或不属于当前项目")
                continue
            if mart_id is None:
                self._broken_mapping_gap("mart_to_ybt", mapping.id, "尚未绑定监管集市字段", [target_id])
                if include_unresolved:
                    mart_id = self._add_placeholder(
                        f"unresolved:mart_to_ybt:{mapping.id}",
                        "待绑定监管集市字段",
                        "MART",
                        mapping_id=mapping.id,
                    )
                else:
                    continue
            self._add_edge(_mapping_edge(
                edge_id=f"mapping:mart_to_ybt:{mapping.id}",
                source_node_id=mart_id,
                target_node_id=target_id,
                mapping_type="mart_to_ybt",
                mapping=mapping,
                evidence=evidence,
            ))

        for mapping in source_rows:
            mart_id = self._add_asset_by_id("mart_field", mapping.mart_field_id, project_id)
            if mart_id is None:
                self._broken_mapping_gap("source_to_mart", mapping.id, "监管集市字段不存在或不属于当前项目")
                continue
            refs = evidence_by_pair.get(("source_to_mart", mapping.id), [])
            evidence = _evidence_payload(refs)
            source_ids: list[str] = []
            for ref in refs:
                if ref.evidence_id is None or ref.evidence_type not in {"source_field", "catalog_column"}:
                    continue
                source_id = self._add_asset_by_id(ref.evidence_type, ref.evidence_id, project_id)
                if source_id is None:
                    self._broken_mapping_gap(
                        "source_to_mart",
                        mapping.id,
                        f"来源证据 {ref.evidence_type}:{ref.evidence_id} 不存在或越出项目范围",
                        [mart_id],
                    )
                    continue
                if ref.evidence_type == "catalog_column":
                    for binding in bindings_by_column.get(int(ref.evidence_id), []):
                        if binding.source_field_id is None:
                            continue
                        bound_source = self._add_asset_by_id("source_field", binding.source_field_id, project_id)
                        if bound_source is not None:
                            self._add_edge({
                                "id": f"catalog_binding:{binding.id}",
                                "source_node_id": bound_source,
                                "target_node_id": source_id,
                                "edge_type": "manual_binding",
                                "relation_source": "catalog_binding",
                                "mapping_type": None,
                                "mapping_id": None,
                                "transformation_type": None,
                                "transformation_expression": None,
                                "join_condition": None,
                                "filter_condition": None,
                                "aggregation_rule": None,
                                "code_mapping_rule": None,
                                "source_line_start": None,
                                "source_line_end": None,
                                "confidence_level": "high",
                                "verification_status": "verified",
                                "evidence_refs": [{
                                    "type": "catalog_import_binding",
                                    "id": binding.id,
                                    "catalog_column_id": binding.catalog_column_id,
                                    "source_field_id": binding.source_field_id,
                                }],
                                "rules": {},
                            })
                if source_id not in source_ids:
                    source_ids.append(source_id)
            if not source_ids:
                self._broken_mapping_gap(
                    "source_to_mart",
                    mapping.id,
                    "已审核口径尚未通过来源字段或数据目录证据绑定到权威资产",
                    [mart_id],
                )
                if include_unresolved:
                    source_ids.append(self._add_placeholder(
                        f"unresolved:source_to_mart:{mapping.id}",
                        "待绑定来源字段",
                        "SOURCE",
                        mapping_id=mapping.id,
                    ))
            for source_id in source_ids:
                self._add_edge(_mapping_edge(
                    edge_id=f"mapping:source_to_mart:{mapping.id}:{_stable_id(source_id)}",
                    source_node_id=source_id,
                    target_node_id=mart_id,
                    mapping_type="source_to_mart",
                    mapping=mapping,
                    evidence=evidence,
                ))

        candidate_count = int(self.db.scalar(select(func.count()).select_from(MartToYbtMapping).where(
            MartToYbtMapping.project_id == project_id,
            MartToYbtMapping.mapping_status != APPROVED_MAPPING_STATUS,
        )) or 0) + int(self.db.scalar(select(func.count()).select_from(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project_id,
            SourceToMartMapping.mapping_status != APPROVED_MAPPING_STATUS,
        )) or 0)
        if candidate_count:
            self.warnings.append(f"已排除 {candidate_count} 条未审核或候选业务映射")

    def _mapping_evidence(
        self,
        project_id: int,
        pairs: list[tuple[str, int]],
    ) -> dict[tuple[str, int], list[MappingEvidenceReference]]:
        if not pairs:
            return {}
        mapping_types = {item[0] for item in pairs}
        mapping_ids = {item[1] for item in pairs}
        allowed = set(pairs)
        rows = self.db.scalars(select(MappingEvidenceReference).where(
            MappingEvidenceReference.project_id == project_id,
            MappingEvidenceReference.mapping_type.in_(mapping_types),
            MappingEvidenceReference.mapping_id.in_(mapping_ids),
        ).order_by(MappingEvidenceReference.id)).all()
        result: dict[tuple[str, int], list[MappingEvidenceReference]] = defaultdict(list)
        for row in rows:
            key = (row.mapping_type, int(row.mapping_id))
            if key in allowed:
                result[key].append(row)
        return result

    def _add_revision_graph(
        self,
        project_id: int,
        revision: LineageRevision,
        *,
        include_unresolved: bool,
    ) -> dict[int, str]:
        node_rows = list(self.db.scalars(select(LineageRevisionNode).where(
            LineageRevisionNode.revision_id == revision.id,
        ).order_by(LineageRevisionNode.id).limit(MAX_REVISION_NODES + 1)).all())
        edge_rows = list(self.db.scalars(select(LineageRevisionEdge).where(
            LineageRevisionEdge.revision_id == revision.id,
        ).order_by(LineageRevisionEdge.id).limit(MAX_REVISION_EDGES + 1)).all())
        if len(node_rows) > MAX_REVISION_NODES or len(edge_rows) > MAX_REVISION_EDGES:
            self.truncated = True
            node_rows = node_rows[:MAX_REVISION_NODES]
            edge_rows = edge_rows[:MAX_REVISION_EDGES]

        output_by_key: dict[str, str | None] = {}
        output_by_lineage_id: dict[int, str] = {}
        for row in node_rows:
            snapshot = dict(row.snapshot_json or {})
            node_key = str(snapshot.get("node_key") or row.node_key)
            output_id = self._add_revision_node(
                project_id,
                revision,
                snapshot,
                include_unresolved=include_unresolved,
            )
            output_by_key[node_key] = output_id
            lineage_node_id = snapshot.get("lineage_node_id") or row.lineage_node_id
            if output_id is not None and lineage_node_id is not None:
                output_by_lineage_id[int(lineage_node_id)] = output_id

        snapshots = [dict(row.snapshot_json or {}) for row in edge_rows]
        version_ids = {
            int(item["script_file_version_id"])
            for item in snapshots
            if item.get("script_file_version_id") is not None
        }
        script_evidence = self._script_evidence(project_id, version_ids)
        for row, snapshot in zip(edge_rows, snapshots, strict=True):
            source_id = output_by_key.get(str(snapshot.get("source_node_key") or ""))
            target_id = output_by_key.get(str(snapshot.get("target_node_key") or ""))
            if source_id is None or target_id is None or source_id == target_id:
                continue
            version_id = snapshot.get("script_file_version_id")
            evidence = [{
                "type": "lineage_edge",
                "lineage_edge_id": snapshot.get("lineage_edge_id") or row.lineage_edge_id,
                "revision_id": revision.id,
            }]
            if version_id is not None and int(version_id) in script_evidence:
                evidence.append(script_evidence[int(version_id)])
            confidence = _confidence(snapshot.get("confidence_level"))
            unresolved = self.nodes[source_id]["unresolved_flag"] or self.nodes[target_id]["unresolved_flag"]
            edge_key = str(snapshot.get("edge_key") or row.edge_key)
            self._add_edge({
                "id": revision_edge_output_id(revision.id, edge_key),
                "source_node_id": source_id,
                "target_node_id": target_id,
                "edge_type": str(snapshot.get("edge_type") or "projection"),
                "relation_source": "technical_lineage",
                "mapping_type": None,
                "mapping_id": None,
                "transformation_type": _text(snapshot.get("transformation_type")),
                "transformation_expression": _text(snapshot.get("transformation_expression"), 4_000),
                "join_condition": _text(snapshot.get("join_condition"), 4_000),
                "filter_condition": _text(snapshot.get("filter_condition"), 4_000),
                "aggregation_rule": _text(snapshot.get("aggregation_rule"), 4_000),
                "code_mapping_rule": _text(snapshot.get("code_mapping_rule"), 4_000),
                "source_line_start": snapshot.get("source_line_start"),
                "source_line_end": snapshot.get("source_line_end"),
                "confidence_level": confidence,
                "verification_status": "unresolved" if unresolved else "verified" if confidence == "high" else "candidate",
                "evidence_refs": evidence,
                "rules": {},
            })
        return output_by_lineage_id

    def _add_revision_node(
        self,
        project_id: int,
        revision: LineageRevision,
        snapshot: dict[str, Any],
        *,
        include_unresolved: bool,
    ) -> str | None:
        canonical = _canonical_ref(snapshot)
        snapshot_display = snapshot.get("display") if isinstance(snapshot.get("display"), dict) else None
        if canonical is not None:
            output_id = self._add_asset_by_id(canonical[0], canonical[1], project_id)
            if output_id is None:
                self.warnings.append(
                    f"版本 #{revision.revision_no} 包含无效或越界资产引用 {canonical[0]}:{canonical[1]}"
                )
                canonical = None
            else:
                node = self.nodes[output_id]
                if snapshot_display:
                    current_display = node.get("display")
                    if current_display != snapshot_display:
                        node["current_display"] = current_display
                    node["display"] = snapshot_display
                    node["layer_code"] = _layer(snapshot_display, snapshot)[0]
                    node["layer_name"] = _layer(snapshot_display, snapshot)[1]
                    node["technical_identifier"] = snapshot_display.get("technical_identifier") or node.get("technical_identifier")
                _append_unique(node["lineage_node_ids"], snapshot.get("lineage_node_id"))
                _append_unique(node["revision_node_keys"], snapshot.get("node_key"))
                _append_unique(node["script_file_version_ids"], snapshot.get("script_file_version_id"))
                identifiers = node["metadata"].setdefault("technical_identifiers", [])
                _append_unique(identifiers, _technical_identifier(snapshot))
                return output_id

        unresolved = bool(snapshot.get("unresolved_flag", True))
        if unresolved and not include_unresolved:
            return None
        node_key = str(snapshot.get("node_key") or snapshot.get("lineage_node_id") or snapshot.get("id"))
        output_id = f"lineage:{revision.id}:{_stable_id(node_key)}"
        display = snapshot_display or _lineage_display(snapshot)
        layer_code, layer_name = _layer(display, snapshot)
        self.nodes.setdefault(output_id, {
            "id": output_id,
            "entity_type": "lineage",
            "canonical_entity_id": None,
            "node_type": str(snapshot.get("node_type") or "unknown"),
            "display": display,
            "current_display": None,
            "layer_code": layer_code,
            "layer_name": layer_name,
            "technical_identifier": display.get("technical_identifier") or _technical_identifier(snapshot),
            "unresolved_flag": unresolved,
            "resolution_status": "unresolved" if unresolved else "technical_only",
            "lineage_node_ids": [int(snapshot["lineage_node_id"])] if snapshot.get("lineage_node_id") is not None else [],
            "revision_node_keys": [node_key],
            "script_file_version_ids": [int(snapshot["script_file_version_id"])] if snapshot.get("script_file_version_id") is not None else [],
            "metadata": {"revision_id": revision.id},
        })
        return output_id

    def _script_evidence(self, project_id: int, version_ids: set[int]) -> dict[int, dict[str, Any]]:
        if not version_ids:
            return {}
        versions = list(self.db.scalars(select(ScriptFileVersion).where(
            ScriptFileVersion.project_id == project_id,
            ScriptFileVersion.id.in_(version_ids),
        )).all())
        script_ids = {int(item.script_file_id) for item in versions}
        scripts = {
            int(item.id): item
            for item in self.db.scalars(select(ScriptFile).where(
                ScriptFile.project_id == project_id,
                ScriptFile.id.in_(script_ids),
            )).all()
        }
        return {
            int(version.id): {
                "type": "script_file_version",
                "script_file_id": int(version.script_file_id),
                "script_file_version_id": int(version.id),
                "version_no": int(version.version_no),
                "relative_path": scripts.get(int(version.script_file_id)).relative_path if int(version.script_file_id) in scripts else None,
                "git_commit_sha": version.git_commit_sha,
                "parse_status": version.parse_status,
            }
            for version in versions
        }

    def _add_asset_by_id(self, entity_type: str, entity_id: int | None, project_id: int) -> str | None:
        if entity_id is None:
            return None
        cache_key = (entity_type, int(entity_id))
        if cache_key in self._asset_cache:
            return self._asset_cache[cache_key]
        model = ROOT_MODELS.get(entity_type)
        if model is None or entity_type == "lineage_node":
            self._asset_cache[cache_key] = None
            return None
        entity = self.db.get(model, int(entity_id))
        if entity is None or int(getattr(entity, "project_id", -1)) != int(project_id):
            self._asset_cache[cache_key] = None
            return None
        result = self._add_asset(entity_type, entity, project_id)
        self._asset_cache[cache_key] = result
        return result

    def _add_asset(self, entity_type: str, entity: Any, project_id: int) -> str:
        if int(getattr(entity, "project_id", -1)) != int(project_id):
            raise LineagePathNotFound("Asset does not belong to the project")
        output_id = f"asset:{entity_type}:{int(entity.id)}"
        if output_id in self.nodes:
            return output_id
        display = self.display.describe(entity_type, entity)
        layer_code, layer_name = _layer(display, {})
        self.nodes[output_id] = {
            "id": output_id,
            "entity_type": entity_type,
            "canonical_entity_id": int(entity.id),
            "node_type": "column" if entity_type.endswith("field") or entity_type == "catalog_column" else "table",
            "display": display,
            "current_display": None,
            "layer_code": layer_code,
            "layer_name": layer_name,
            "technical_identifier": display.get("technical_identifier"),
            "unresolved_flag": False,
            "resolution_status": "resolved",
            "lineage_node_ids": [],
            "revision_node_keys": [],
            "script_file_version_ids": [],
            "metadata": {},
        }
        return output_id

    def _add_live_lineage_node(self, node: LineageNode, *, include_unresolved: bool) -> str | None:
        canonical = _canonical_ref({
            "target_field_id": node.target_field_id,
            "mart_field_id": node.mart_field_id,
            "source_field_id": node.source_field_id,
            "catalog_column_id": node.catalog_column_id,
        })
        if canonical is not None:
            return self._add_asset_by_id(canonical[0], canonical[1], node.project_id)
        if node.unresolved_flag and not include_unresolved:
            return None
        output_id = f"lineage-node:{node.id}"
        display = self.display.describe_lineage_node(node)
        layer_code, layer_name = _layer(display, {
            "database_name": node.database_name,
            "schema_name": node.schema_name,
            "table_name": node.table_name,
        })
        self.nodes[output_id] = {
            "id": output_id,
            "entity_type": "lineage",
            "canonical_entity_id": None,
            "node_type": node.node_type,
            "display": display,
            "current_display": None,
            "layer_code": layer_code,
            "layer_name": layer_name,
            "technical_identifier": display.get("technical_identifier"),
            "unresolved_flag": bool(node.unresolved_flag),
            "resolution_status": "unresolved" if node.unresolved_flag else "technical_only",
            "lineage_node_ids": [int(node.id)],
            "revision_node_keys": [],
            "script_file_version_ids": [int(node.script_file_version_id)] if node.script_file_version_id else [],
            "metadata": {"compatibility_view": True},
        }
        return output_id

    def _add_placeholder(self, output_id: str, label: str, layer_code: str, *, mapping_id: int) -> str:
        self.nodes.setdefault(output_id, {
            "id": output_id,
            "entity_type": "unresolved",
            "canonical_entity_id": None,
            "node_type": "column",
            "display": {
                "id": mapping_id,
                "canonical_entity_id": None,
                "entity_type": "unresolved",
                "display_name": label,
                "business_name": None,
                "comment": None,
                "aliases": [],
                "description": None,
                "technical_name": None,
                "technical_identifier": None,
                "qualified_technical_name": None,
                "display_name_source": "missing",
                "label_quality": "missing",
                "layer_code": layer_code,
                "layer_name": LAYER_NAMES.get(layer_code, layer_code),
                "system_name": None,
            },
            "current_display": None,
            "layer_code": layer_code,
            "layer_name": LAYER_NAMES.get(layer_code, layer_code),
            "technical_identifier": None,
            "unresolved_flag": True,
            "resolution_status": "unresolved",
            "lineage_node_ids": [],
            "revision_node_keys": [],
            "script_file_version_ids": [],
            "metadata": {"mapping_id": mapping_id},
        })
        return output_id

    def _add_edge(self, edge: dict[str, Any]) -> None:
        if edge["source_node_id"] not in self.nodes or edge["target_node_id"] not in self.nodes:
            return
        self.edges.setdefault(str(edge["id"]), edge)

    def _broken_mapping_gap(
        self,
        mapping_type: str,
        mapping_id: int,
        problem: str,
        affected_assets: list[str] | None = None,
    ) -> None:
        self.gaps.append({
            "gap_type": "missing_asset_binding",
            "problem_statement": f"{mapping_type} #{mapping_id}：{problem}",
            "recommended_change": "为已审核口径补充权威字段绑定和可定位证据，不要仅依赖表名/字段名字符串摘要",
            "alternative_options": ["绑定 SourceField", "绑定 CatalogColumn", "退回口径审核补充证据"],
            "rationale": "端到端血缘必须通过项目内实体关系校验，字符串相似不能成为正式事实",
            "evidence_refs": [{"type": "mapping", "mapping_type": mapping_type, "mapping_id": mapping_id}],
            "affected_assets": affected_assets or [],
            "estimated_impact": "阻断完整来源追溯和自动生成开发取数方案",
            "confidence_level": "high",
            "approval_status": "pending_review",
        })

    def _walk_paths(
        self,
        root_node_id: str,
        *,
        direction: str,
        depth: int,
        max_paths: int,
    ) -> tuple[list[dict[str, Any]], list[str], list[str], bool]:
        outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.edges.values():
            outgoing[edge["source_node_id"]].append(edge)
            incoming[edge["target_node_id"]].append(edge)
        for values in (*outgoing.values(), *incoming.values()):
            values.sort(key=lambda item: str(item["id"]))

        queue = deque([(root_node_id, [root_node_id], [], [])])
        results: list[dict[str, Any]] = []
        selected_nodes: list[str] = []
        selected_edges: list[str] = []
        traversal_truncated = False
        while queue and len(results) < max_paths:
            current, node_ids, edge_ids, steps = queue.popleft()
            candidates: list[tuple[dict[str, Any], str, str]] = []
            if direction in {"downstream", "both"}:
                candidates.extend((edge, edge["target_node_id"], "forward") for edge in outgoing.get(current, []))
            if direction in {"upstream", "both"}:
                candidates.extend((edge, edge["source_node_id"], "reverse") for edge in incoming.get(current, []))
            candidates = [item for item in candidates if item[1] not in node_ids]
            candidates.sort(key=lambda item: (str(item[0]["id"]), item[2]))
            at_limit = len(edge_ids) >= depth
            if not candidates or at_limit:
                if at_limit and candidates:
                    traversal_truncated = True
                path = self._path_payload(
                    root_node_id,
                    node_ids,
                    edge_ids,
                    steps,
                    direction=direction,
                    terminal_has_more=bool(candidates),
                )
                results.append(path)
                for node_id in node_ids:
                    if node_id not in selected_nodes:
                        selected_nodes.append(node_id)
                for edge_id in edge_ids:
                    if edge_id not in selected_edges:
                        selected_edges.append(edge_id)
                continue
            for edge, next_node, traversed in candidates:
                queue.append((
                    next_node,
                    [*node_ids, next_node],
                    [*edge_ids, edge["id"]],
                    [*steps, {
                        "edge_id": edge["id"],
                        "from_node_id": current,
                        "to_node_id": next_node,
                        "traversed": traversed,
                    }],
                ))
        if queue:
            traversal_truncated = True
        if not results:
            results.append(self._path_payload(
                root_node_id,
                [root_node_id],
                [],
                [],
                direction=direction,
                terminal_has_more=False,
            ))
            selected_nodes.append(root_node_id)
        return results, selected_nodes, selected_edges, traversal_truncated

    def _path_payload(
        self,
        root_node_id: str,
        node_ids: list[str],
        edge_ids: list[str],
        steps: list[dict[str, Any]],
        *,
        direction: str,
        terminal_has_more: bool,
    ) -> dict[str, Any]:
        edges = [self.edges[item] for item in edge_ids]
        unresolved = [item for item in node_ids if self.nodes[item]["unresolved_flag"]]
        terminal = self.nodes[node_ids[-1]]
        if direction == "upstream":
            terminal_layer_complete = terminal["layer_code"] in {"SOURCE", "CATALOG"}
        elif direction == "downstream":
            terminal_layer_complete = terminal["layer_code"] == "TARGET"
        else:
            terminal_layer_complete = not terminal_has_more
        complete = bool(edge_ids) and not unresolved and not terminal_has_more and terminal_layer_complete
        confidence = _path_confidence(edges, unresolved, complete)
        all_forward = steps and all(item["traversed"] == "forward" for item in steps)
        all_reverse = steps and all(item["traversed"] == "reverse" for item in steps)
        data_flow_nodes = node_ids if all_forward else list(reversed(node_ids)) if all_reverse else node_ids
        evidence = _unique_dicts(
            value
            for edge in edges
            for value in edge.get("evidence_refs", [])
        )
        path_token = json.dumps({"nodes": node_ids, "edges": edge_ids}, sort_keys=True, ensure_ascii=False)
        return {
            "path_id": f"path:{_stable_id(path_token)}",
            "root_node_id": root_node_id,
            "terminal_node_id": node_ids[-1],
            "direction": direction,
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "traversal_steps": steps,
            "data_flow_node_ids": data_flow_nodes,
            "complete": complete,
            "confidence": confidence,
            "unresolved_node_ids": unresolved,
            "evidence_refs": evidence,
        }

    def _add_result_gaps(
        self,
        root_node_id: str,
        paths: list[dict[str, Any]],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        direction: str,
        revision: LineageRevision | None,
    ) -> None:
        if not edges:
            self.gaps.append(_gap(
                "no_lineage_path",
                "当前根字段没有可用的已审核映射或技术血缘路径",
                "补充并审核 Source→Mart、Mart→监管输出映射，同时绑定脚本解析血缘",
                [root_node_id],
                "high",
            ))
        elif not any(edge["relation_source"] == "technical_lineage" for edge in edges):
            self.gaps.append(_gap(
                "missing_technical_evidence",
                "业务取数口径已连通，但路径中没有所选版本的跑批脚本血缘证据",
                "上传或同步对应跑批脚本，完成字段绑定并发布新的血缘版本",
                [root_node_id],
                "high",
            ))
        if revision is None:
            self.gaps.append(_gap(
                "missing_lineage_revision",
                "项目尚无已发布的正式血缘版本",
                "构建、审核并发布项目级血缘版本后再冻结需求快照",
                [root_node_id],
                "high",
            ))
        if paths and not any(item["complete"] for item in paths):
            expected = "源系统或数据目录" if direction == "upstream" else "监管输出" if direction == "downstream" else "完整终点"
            self.gaps.append(_gap(
                "incomplete_terminal_path",
                f"当前路径尚未无缺口地到达{expected}",
                "补齐缺失层级、关联键、时间字段或权威资产绑定，并经人工审核确认",
                [root_node_id],
                "medium",
            ))
        missing_labels = [item["id"] for item in nodes if item["display"].get("label_quality") == "missing"]
        if missing_labels:
            self.gaps.append(_gap(
                "missing_business_comment",
                f"路径中有 {len(missing_labels)} 个资产缺少可用中文业务备注",
                "在元数据目录维护并确认中文业务名称/字段备注，技术名称仅保留为次要信息",
                missing_labels,
                "medium",
            ))


def _mapping_edge(
    *,
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    mapping_type: str,
    mapping: SourceToMartMapping | MartToYbtMapping,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(mapping, SourceToMartMapping):
        aggregation = mapping.merge_rule or mapping.priority_rule
        rules = {
            "business_rule": mapping.business_rule,
            "priority_rule": mapping.priority_rule,
            "merge_rule": mapping.merge_rule,
            "null_handling_rule": mapping.null_handling_rule,
            "exception_rule": mapping.exception_rule,
            "quality_check_rule": mapping.quality_check_rule,
        }
    else:
        aggregation = mapping.reporting_condition
        rules = {
            "business_rule": mapping.business_rule,
            "reporting_condition": mapping.reporting_condition,
            "null_handling_rule": mapping.null_handling_rule,
            "validation_rule": mapping.validation_rule,
        }
    return {
        "id": edge_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "edge_type": "manual_binding",
        "relation_source": "business_mapping",
        "mapping_type": mapping_type,
        "mapping_id": int(mapping.id),
        "transformation_type": "business_rule" if mapping.business_rule else None,
        "transformation_expression": _text(mapping.business_rule, 4_000),
        "join_condition": _text(mapping.join_condition, 4_000),
        "filter_condition": _text(mapping.filter_condition, 4_000),
        "aggregation_rule": _text(aggregation, 4_000),
        "code_mapping_rule": _text(mapping.code_mapping_rule, 4_000),
        "source_line_start": None,
        "source_line_end": None,
        "confidence_level": _confidence(mapping.confidence_level),
        "verification_status": "verified",
        "evidence_refs": [
            {
                "type": "mapping",
                "mapping_type": mapping_type,
                "mapping_id": int(mapping.id),
                "mapping_status": mapping.mapping_status,
            },
            *evidence,
        ],
        "rules": {key: _text(value, 4_000) for key, value in rules.items() if value},
    }


def _canonical_ref(snapshot: dict[str, Any]) -> tuple[str, int] | None:
    for entity_type, key in (
        ("target_field", "target_field_id"),
        ("mart_field", "mart_field_id"),
        ("source_field", "source_field_id"),
        ("catalog_column", "catalog_column_id"),
    ):
        value = snapshot.get(key)
        if value is not None:
            return entity_type, int(value)
    return None


def _evidence_payload(rows: Iterable[MappingEvidenceReference]) -> list[dict[str, Any]]:
    return [{
        "type": "mapping_evidence",
        "id": int(row.id),
        "evidence_type": row.evidence_type,
        "evidence_id": row.evidence_id,
        "source_name": _text(row.source_name, 500),
        "location": _text(row.location_text, 500),
        "summary": _text(row.evidence_summary, 1_000),
    } for row in rows]


def _technical_identifier(snapshot: dict[str, Any]) -> str | None:
    parts = [
        _text(snapshot.get("database_name"), 255),
        _text(snapshot.get("schema_name"), 255),
        _text(snapshot.get("table_name"), 255),
        _text(snapshot.get("column_name"), 255),
    ]
    result = ".".join(item for item in parts if item)
    return result or _text(snapshot.get("logical_name"), 1_000)


def _lineage_display(snapshot: dict[str, Any]) -> dict[str, Any]:
    technical = _technical_identifier(snapshot)
    layer_code, layer_name = _layer({}, snapshot)
    return {
        "id": snapshot.get("lineage_node_id") or snapshot.get("id"),
        "canonical_entity_id": None,
        "entity_type": "lineage",
        "display_name": technical or "缺少业务备注",
        "business_name": None,
        "comment": None,
        "aliases": [],
        "description": None,
        "technical_name": snapshot.get("column_name") or snapshot.get("logical_name"),
        "technical_identifier": technical,
        "qualified_technical_name": technical,
        "display_name_source": "technical_name" if technical else "missing",
        "label_quality": "missing",
        "layer_code": layer_code,
        "layer_name": layer_name,
        "system_name": None,
    }


def _layer(display: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, str]:
    explicit = _text(display.get("layer_code") if isinstance(display, dict) else None, 50)
    if explicit and explicit.upper() != "UNKNOWN":
        code = explicit.upper()
        return code, LAYER_NAMES.get(code, display.get("layer_name") or code)
    haystack = ".".join(str(snapshot.get(key) or "") for key in (
        "database_name", "schema_name", "table_name", "logical_name",
    )).upper()
    for code in ("SOURCE", "ODS", "DWD", "DWS", "MART", "TARGET"):
        if code in haystack:
            return code, LAYER_NAMES.get(code, code)
    if any(token in haystack for token in ("YBT", "EAST", "1104")):
        return "TARGET", LAYER_NAMES["TARGET"]
    if display.get("entity_type") == "catalog_column":
        return "CATALOG", LAYER_NAMES["CATALOG"]
    return "UNKNOWN", LAYER_NAMES["UNKNOWN"]


def _gap(
    gap_type: str,
    problem: str,
    recommendation: str,
    affected_assets: list[str],
    confidence: str,
) -> dict[str, Any]:
    return {
        "gap_type": gap_type,
        "problem_statement": problem,
        "recommended_change": recommendation,
        "alternative_options": [],
        "rationale": "正式需求文档只能引用可验证、可按版本回看的项目内事实",
        "evidence_refs": [],
        "affected_assets": affected_assets,
        "estimated_impact": "影响需求文档完整性、开发可执行性或审计追溯",
        "confidence_level": confidence,
        "approval_status": "pending_review",
    }


def _dedupe_gaps(gaps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for gap in gaps:
        key = json.dumps({
            "gap_type": gap.get("gap_type"),
            "problem_statement": gap.get("problem_statement"),
            "affected_assets": gap.get("affected_assets", []),
        }, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            result.append(gap)
    return result


def _unique_dicts(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _path_confidence(edges: list[dict[str, Any]], unresolved: list[str], complete: bool) -> str:
    if unresolved or not edges:
        return "low"
    rank = min((_CONFIDENCE_RANK.get(_confidence(item.get("confidence_level")), 1) for item in edges), default=1)
    if not complete:
        rank = min(rank, 1)
    return ("low", "medium", "high")[rank]


def _overall_confidence(paths: list[dict[str, Any]], unresolved: list[dict[str, Any]], warnings: list[str]) -> str:
    if unresolved or not paths:
        return "low"
    rank = min((_CONFIDENCE_RANK.get(str(item.get("confidence")), 1) for item in paths), default=1)
    if warnings:
        rank = min(rank, 1)
    return ("low", "medium", "high")[rank]


def _confidence(value: Any) -> str:
    result = str(value or "medium").strip().lower()
    return result if result in _CONFIDENCE_RANK else "medium"


def _append_unique(values: list[Any], value: Any) -> None:
    if value is None:
        return
    normalized = int(value) if isinstance(value, int) or str(value).isdigit() else str(value)
    if normalized not in values:
        values.append(normalized)


def _stable_id(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:20]


def revision_edge_output_id(revision_id: int, edge_key: Any) -> str:
    """Return the stable UI id used for one immutable revision edge."""

    return f"revision:{int(revision_id)}:edge:{_stable_id(edge_key)}"


def _text(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return redact_content(result[:limit]) if result else None


__all__ = ["LineagePathNotFound", "LineagePathResolver"]
