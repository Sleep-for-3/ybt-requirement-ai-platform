"""Canonical, immutable project-level lineage revisions.

The parser tables remain the source of technical facts.  This module creates
an immutable membership/snapshot projection over the latest script versions so
that a graph can be read and compared without mixing historical versions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ImpactAnalysis,
    LineageEdge,
    LineageNode,
    LineageRevision,
    LineageRevisionEdge,
    LineageRevisionNode,
    Project,
    ScriptChangeSet,
    ScriptFile,
    ScriptFileVersion,
)
from app.services.asset_display import AssetDisplayResolver


PARSER_VERSION = "lineage-revision-v1"
_PARSE_WARNING_STATUSES = {"pending", "failed", "partially_parsed"}
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
# Minimum column-name similarity before a removed/added pair is accepted as a
# rename. Below this threshold the two nodes stay visible as a removal and an
# addition so a genuine drop cannot be hidden behind a fuzzy match.
_RENAME_SIMILARITY_THRESHOLD = 0.65


@dataclass(frozen=True)
class RevisionBuildResult:
    revision: LineageRevision
    idempotent: bool
    node_count: int
    edge_count: int


class LineageRevisionService:
    def __init__(self, db: Session):
        self.db = db

    def build(
        self,
        project_id: int,
        *,
        created_by: int | None = None,
        trigger_type: str = "manual",
        source_commit_sha: str | None = None,
        script_version_ids: Iterable[int] | None = None,
        status: str | None = None,
        publish: bool = False,
    ) -> RevisionBuildResult:
        # PostgreSQL serializes revision-number allocation per project. SQLite
        # ignores FOR UPDATE, so the unique constraints plus the savepoint
        # retry below remain the final concurrency guard there.
        project = self.db.scalar(
            select(Project).where(Project.id == int(project_id)).with_for_update()
        )
        if project is None:
            raise ValueError("Project not found")

        versions = self._select_versions(project.id, script_version_ids)
        nodes = self._select_nodes(project.id, versions)
        edges = self._select_edges(project.id, versions)
        node_snapshots, node_key_by_id = self._build_node_snapshots(project.id, nodes)
        representative_id_by_key = {str(item["node_key"]): int(item["id"]) for item in node_snapshots}
        edge_snapshots = self._build_edge_snapshots(edges, node_key_by_id, representative_id_by_key)
        manifest = self._source_manifest(versions)
        warnings = self._warnings(versions, nodes, edges)
        graph_hash = _hash_json({
            "nodes": [_semantic_node(item) for item in node_snapshots],
            "edges": [_semantic_edge(item) for item in edge_snapshots],
            # Version identity is part of the auditable project snapshot, but
            # raw file hashes are intentionally excluded so a comment/format
            # change can be classified as non-semantic by the diff service.
            "source_manifest": [
                {
                    key: item.get(key)
                    for key in ("script_file_id", "version_id", "version_no", "normalized_hash", "parse_status", "enabled")
                }
                for item in manifest
            ],
        })

        resolved_status = status or ("needs_review" if warnings else "draft")
        if resolved_status not in {"draft", "needs_review", "failed"}:
            raise ValueError("Invalid lineage revision status")
        if publish and warnings:
            resolved_status = "needs_review"
        if publish and resolved_status == "failed":
            raise ValueError("Failed lineage revision cannot be published")

        # A concurrent worker may allocate the same revision number or create
        # the same graph after our first lookup. Keep caller-owned parser facts
        # intact by rolling back only this revision savepoint, then re-read or
        # retry the number allocation.
        for attempt in range(3):
            existing = self.db.scalar(select(LineageRevision).where(
                LineageRevision.project_id == project.id,
                LineageRevision.graph_hash == graph_hash,
            ))
            if existing is not None:
                self._finalize_build_status(existing, publish_requested=publish)
                return RevisionBuildResult(existing, True, existing.node_count, existing.edge_count)

            parent = self.db.scalar(select(LineageRevision).where(
                LineageRevision.project_id == project.id,
            ).order_by(LineageRevision.revision_no.desc()).limit(1))
            revision = LineageRevision(
                institution_id=project.institution_id,
                project_id=project.id,
                revision_no=(parent.revision_no if parent else 0) + 1,
                parent_revision_id=parent.id if parent else None,
                trigger_type=(trigger_type or "manual")[:50],
                source_commit_sha=source_commit_sha,
                parser_version=PARSER_VERSION,
                graph_hash=graph_hash,
                status=resolved_status,
                warnings_json=warnings,
                source_manifest_json=manifest,
                node_count=len(node_snapshots),
                edge_count=len(edge_snapshots),
                created_by=created_by,
                published_at=None,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(revision)
                    self.db.flush()
                    for snapshot in node_snapshots:
                        self.db.add(LineageRevisionNode(
                            revision_id=revision.id,
                            lineage_node_id=int(snapshot["lineage_node_id"]),
                            node_key=str(snapshot["node_key"]),
                            snapshot_hash=_hash_json(_semantic_node(snapshot)),
                            snapshot_json=snapshot,
                        ))
                    for snapshot in edge_snapshots:
                        self.db.add(LineageRevisionEdge(
                            revision_id=revision.id,
                            lineage_edge_id=int(snapshot["lineage_edge_id"]),
                            edge_key=str(snapshot["edge_key"]),
                            snapshot_hash=_hash_json(_semantic_edge(snapshot)),
                            snapshot_json=snapshot,
                        ))
                    self.db.flush()
            except IntegrityError as exc:
                self.db.expire_all()
                existing = self.db.scalar(select(LineageRevision).where(
                    LineageRevision.project_id == project.id,
                    LineageRevision.graph_hash == graph_hash,
                ))
                if existing is not None:
                    self._finalize_build_status(existing, publish_requested=publish)
                    return RevisionBuildResult(existing, True, existing.node_count, existing.edge_count)
                if attempt == 2:
                    raise RuntimeError("Concurrent lineage revision allocation did not converge") from exc
                continue

            self._finalize_build_status(revision, publish_requested=publish)
            return RevisionBuildResult(revision, False, len(node_snapshots), len(edge_snapshots))

        raise RuntimeError("Concurrent lineage revision allocation did not converge")

    def _finalize_build_status(self, revision: LineageRevision, *, publish_requested: bool) -> None:
        if revision.status in {"published", "superseded", "failed"}:
            return
        readiness = self.publication_readiness(revision)
        if publish_requested:
            if readiness["ready"]:
                self.publish(revision, commit=False)
            else:
                revision.status = "needs_review"
                self.db.flush()
            return
        if (
            revision.status == "draft"
            and readiness["semantic_changed"]
            and _SEVERITY_RANK.get(str(readiness["severity"]), 0) >= _SEVERITY_RANK["medium"]
        ):
            revision.status = "needs_review"
            self.db.flush()

    def publish(self, revision: LineageRevision, *, commit: bool = True) -> LineageRevision:
        if revision.status == "published":
            return revision
        if revision.status == "superseded":
            raise ValueError("Superseded lineage revision cannot be republished; create a new revision instead")
        if revision.status == "failed":
            raise ValueError("Failed lineage revision cannot be published")
        readiness = self.publication_readiness(revision)
        if not readiness["ready"]:
            raise ValueError("Lineage revision is not publishable: " + "; ".join(readiness["blockers"]))
        self._supersede_previous(revision)
        revision.status = "published"
        revision.published_at = revision.published_at or datetime.now(UTC)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(revision)
        return revision

    def publication_readiness(self, revision: LineageRevision) -> dict[str, Any]:
        """Return the deterministic review gate used by both API and service.

        Parser warnings are never manually overridden. High/critical semantic
        differences require every matching impact analysis to finish the
        existing lineage_change_review workflow before publication.
        """

        blockers = list(revision.warnings_json or [])
        current = self.db.scalar(select(LineageRevision).where(
            LineageRevision.project_id == revision.project_id,
            LineageRevision.status == "published",
            LineageRevision.id != revision.id,
        ).order_by(LineageRevision.revision_no.desc()).limit(1))
        severity = "low"
        semantic_changed = False
        impact_ids: list[int] = []
        pending_impact_ids: list[int] = []
        review_required = False
        if current is not None:
            comparison = self.diff(revision, current)
            severity = str(comparison["severity"])
            semantic_changed = bool(comparison["semantic_changed"])
            review_required = semantic_changed and _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK["high"]
            if review_required:
                impacts = self._transition_impacts(current, revision)
                impact_ids = [int(item.id) for item in impacts]
                pending_impact_ids = [
                    int(item.id)
                    for item in impacts
                    if item.status not in {"reviewed", "approved", "closed"}
                ]
                if not impacts:
                    blockers.append("高风险血缘变化缺少影响分析与审核记录")
                elif pending_impact_ids:
                    blockers.append(
                        "高风险血缘变化尚有未完成的影响审核："
                        + ", ".join(str(item) for item in pending_impact_ids)
                    )
        return {
            "ready": not blockers,
            "review_required": review_required,
            "severity": severity,
            "semantic_changed": semantic_changed,
            "baseline_revision_id": current.id if current is not None else None,
            "impact_ids": impact_ids,
            "pending_impact_ids": pending_impact_ids,
            "blockers": blockers,
        }

    def _transition_impacts(
        self,
        baseline: LineageRevision,
        revision: LineageRevision,
    ) -> list[ImpactAnalysis]:
        old_manifest = {
            int(item["script_file_id"]): item
            for item in (baseline.source_manifest_json or [])
            if item.get("script_file_id") is not None
        }
        new_manifest = {
            int(item["script_file_id"]): item
            for item in (revision.source_manifest_json or [])
            if item.get("script_file_id") is not None
        }
        changed_script_ids = {
            script_id
            for script_id in old_manifest.keys() | new_manifest.keys()
            if old_manifest.get(script_id, {}).get("version_id")
            != new_manifest.get(script_id, {}).get("version_id")
        }
        if not changed_script_ids:
            return []
        change_sets = list(self.db.scalars(select(ScriptChangeSet).where(
            ScriptChangeSet.project_id == revision.project_id,
            ScriptChangeSet.script_file_id.in_(changed_script_ids),
            or_(
                ScriptChangeSet.to_version_id.in_([
                    int(item["version_id"])
                    for item in new_manifest.values()
                    if item.get("version_id") is not None
                ]),
                ScriptChangeSet.from_version_id.in_([
                    int(item["version_id"])
                    for item in old_manifest.values()
                    if item.get("version_id") is not None
                ]),
            ),
        )).all())
        if not change_sets:
            return []
        return list(self.db.scalars(select(ImpactAnalysis).where(
            ImpactAnalysis.project_id == revision.project_id,
            ImpactAnalysis.change_set_id.in_([int(item.id) for item in change_sets]),
            ImpactAnalysis.severity.in_(("high", "critical")),
        ).order_by(ImpactAnalysis.id)).all())

    def get(self, revision_id: int, *, project_id: int | None = None) -> LineageRevision | None:
        revision = self.db.get(LineageRevision, int(revision_id))
        if revision is None or (project_id is not None and revision.project_id != int(project_id)):
            return None
        return revision

    def list(self, project_id: int, *, status: str | None = None, limit: int = 100) -> list[LineageRevision]:
        query = select(LineageRevision).where(LineageRevision.project_id == int(project_id))
        if status:
            query = query.where(LineageRevision.status == status)
        return list(self.db.scalars(query.order_by(LineageRevision.revision_no.desc()).limit(min(max(limit, 1), 500))).all())

    def members(self, revision: LineageRevision) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes = list(self.db.scalars(select(LineageRevisionNode).where(
            LineageRevisionNode.revision_id == revision.id,
        ).order_by(LineageRevisionNode.id)).all())
        edges = list(self.db.scalars(select(LineageRevisionEdge).where(
            LineageRevisionEdge.revision_id == revision.id,
        ).order_by(LineageRevisionEdge.id)).all())
        return [dict(item.snapshot_json or {}) for item in nodes], [dict(item.snapshot_json or {}) for item in edges]

    def diff(self, revision: LineageRevision, compare_to: LineageRevision) -> dict[str, Any]:
        if revision.project_id != compare_to.project_id:
            raise ValueError("Lineage revisions belong to different projects")
        new_nodes, new_edges = self.members(revision)
        old_nodes, old_edges = self.members(compare_to)
        items: list[dict[str, Any]] = []

        old_node_map = {item["node_key"]: item for item in old_nodes}
        new_node_map = {item["node_key"]: item for item in new_nodes}
        # One column rename is one reviewable edit.  Match renames first and
        # emit a single ``field_renamed`` item per pair instead of forcing a
        # reviewer to reconcile a removal, an addition and a rename for the
        # same column.  Only unmatched keys stay visible as added/removed.
        renamed_pairs, unmatched_removed, unmatched_added = _match_renamed_nodes(old_node_map, new_node_map)
        for key in sorted(unmatched_removed):
            items.append(_diff_item("node_removed", "lineage_node", old_node_map[key], {}, "critical"))
        for key in sorted(unmatched_added):
            items.append(_diff_item("node_added", "lineage_node", {}, new_node_map[key], "medium"))
        for old_node, new_node, ratio in renamed_pairs:
            renamed = _diff_item("field_renamed", "lineage_node", old_node, new_node, "high", ["column_name"])
            renamed["match_confidence"] = round(ratio, 4)
            items.append(renamed)
        for key in sorted(old_node_map.keys() & new_node_map.keys()):
            if _semantic_node(old_node_map[key]) != _semantic_node(new_node_map[key]):
                items.append(_diff_item("node_changed", "lineage_node", old_node_map[key], new_node_map[key], "medium"))

        old_edge_map = {item["edge_key"]: item for item in old_edges}
        new_edge_map = {item["edge_key"]: item for item in new_edges}
        for key in sorted(old_edge_map.keys() - new_edge_map.keys()):
            items.append(_diff_item("edge_removed", "lineage_edge", old_edge_map[key], {}, "critical"))
        for key in sorted(new_edge_map.keys() - old_edge_map.keys()):
            items.append(_diff_item("edge_added", "lineage_edge", {}, new_edge_map[key], "medium"))
        for key in sorted(old_edge_map.keys() & new_edge_map.keys()):
            old_edge = old_edge_map[key]
            new_edge = new_edge_map[key]
            changed_fields = [
                field for field in (
                    "edge_type", "transformation_type", "transformation_expression",
                    "join_condition", "filter_condition", "aggregation_rule", "code_mapping_rule",
                    "confidence_level",
                ) if _normal(old_edge.get(field)) != _normal(new_edge.get(field))
            ]
            if changed_fields:
                # Keep one auditable item per semantic rule.  A single SQL
                # edge can change its join and filter at the same time; a
                # single coarse ``edge_changed`` item would hide one of the
                # governance decisions from reviewers.
                emitted: set[str] = set()
                for field in changed_fields:
                    category, severity = _edge_change_category([field])
                    if category in emitted:
                        continue
                    emitted.add(category)
                    items.append(_diff_item(category, "lineage_edge", old_edge, new_edge, severity, [field]))

        old_manifest = {int(item["script_file_id"]): item for item in (compare_to.source_manifest_json or []) if item.get("script_file_id") is not None}
        new_manifest = {int(item["script_file_id"]): item for item in (revision.source_manifest_json or []) if item.get("script_file_id") is not None}
        for script_id in sorted(old_manifest.keys() - new_manifest.keys()):
            items.append(_diff_item("script_removed", "script_file", old_manifest[script_id], {}, "critical"))
        for script_id in sorted(new_manifest.keys() - old_manifest.keys()):
            items.append(_diff_item("script_added", "script_file", {}, new_manifest[script_id], "medium"))
        for script_id in sorted(old_manifest.keys() & new_manifest.keys()):
            old_status = old_manifest[script_id].get("parse_status")
            new_status = new_manifest[script_id].get("parse_status")
            if old_status != new_status:
                items.append(_diff_item("parse_quality_changed", "script_file", old_manifest[script_id], new_manifest[script_id], "high"))

        if not items:
            items.append(_diff_item("non_semantic", "lineage_revision", {"revision_id": compare_to.id}, {"revision_id": revision.id}, "low"))
        severity = max((str(item["severity"]) for item in items), key=lambda value: _SEVERITY_RANK.get(value, 0))
        return {
            "project_id": revision.project_id,
            "from_revision_id": compare_to.id,
            "to_revision_id": revision.id,
            "semantic_changed": any(item["change_category"] != "non_semantic" for item in items),
            "severity": severity,
            "items": items,
            "summary": {
                "categories": sorted({item["change_category"] for item in items}),
                "from_revision_no": compare_to.revision_no,
                "to_revision_no": revision.revision_no,
                "from_graph_hash": compare_to.graph_hash,
                "to_graph_hash": revision.graph_hash,
            },
        }

    def _select_versions(self, project_id: int, script_version_ids: Iterable[int] | None) -> list[ScriptFileVersion]:
        if script_version_ids is not None:
            ids = sorted({int(item) for item in script_version_ids})
            if not ids:
                return []
            versions = list(self.db.scalars(select(ScriptFileVersion).where(
                ScriptFileVersion.project_id == project_id,
                ScriptFileVersion.id.in_(ids),
            ).order_by(ScriptFileVersion.id)).all())
            if len(versions) != len(ids):
                raise ValueError("One or more script versions do not belong to the project")
            return versions
        scripts = list(self.db.scalars(select(ScriptFile).where(
            ScriptFile.project_id == project_id,
            ScriptFile.enabled.is_(True),
        ).order_by(ScriptFile.id)).all())
        result: list[ScriptFileVersion] = []
        for script in scripts:
            if script.current_version_no <= 0:
                continue
            version = self.db.scalar(select(ScriptFileVersion).where(
                ScriptFileVersion.script_file_id == script.id,
                ScriptFileVersion.version_no == script.current_version_no,
            ))
            if version is not None:
                result.append(version)
        return result

    def _select_nodes(self, project_id: int, versions: list[ScriptFileVersion]) -> list[LineageNode]:
        ids = [item.id for item in versions]
        if not ids:
            return []
        return list(self.db.scalars(select(LineageNode).where(
            LineageNode.project_id == project_id,
            LineageNode.script_file_version_id.in_(ids),
        ).order_by(LineageNode.id)).all())

    def _select_edges(self, project_id: int, versions: list[ScriptFileVersion]) -> list[LineageEdge]:
        ids = [item.id for item in versions]
        if not ids:
            return []
        return list(self.db.scalars(select(LineageEdge).where(
            LineageEdge.project_id == project_id,
            LineageEdge.script_file_version_id.in_(ids),
            LineageEdge.enabled.is_(True),
        ).order_by(LineageEdge.id)).all())

    def _build_node_snapshots(self, project_id: int, nodes: list[LineageNode]) -> tuple[list[dict[str, Any]], dict[int, str]]:
        resolver = AssetDisplayResolver(self.db)
        grouped: dict[str, list[LineageNode]] = {}
        for node in nodes:
            grouped.setdefault(_node_key(node), []).append(node)
        snapshots: list[dict[str, Any]] = []
        node_key_by_id: dict[int, str] = {}
        for key in sorted(grouped):
            group = sorted(grouped[key], key=lambda item: (bool(item.unresolved_flag), item.id))
            representative = group[0]
            for item in group:
                node_key_by_id[item.id] = key
            snapshots.append(_node_snapshot(representative, key, resolver))
        return snapshots, node_key_by_id

    def _build_edge_snapshots(
        self,
        edges: list[LineageEdge],
        node_key_by_id: dict[int, str],
        representative_id_by_key: dict[str, int],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[tuple[LineageEdge, str, str]]] = {}
        for edge in edges:
            source_key = node_key_by_id.get(edge.source_node_id)
            target_key = node_key_by_id.get(edge.target_node_id)
            if source_key is None or target_key is None:
                continue
            base = f"{source_key}->{target_key}|{_normal(edge.edge_type)}"
            grouped.setdefault(base, []).append((edge, source_key, target_key))
        snapshots: list[dict[str, Any]] = []
        for base in sorted(grouped):
            rows = sorted(grouped[base], key=lambda item: (_edge_sort_key(item[0]), item[0].id))
            for ordinal, (edge, source_key, target_key) in enumerate(rows):
                snapshots.append(_edge_snapshot(
                    edge,
                    f"{base}#{ordinal}",
                    source_key,
                    target_key,
                    representative_id_by_key.get(source_key, edge.source_node_id),
                    representative_id_by_key.get(target_key, edge.target_node_id),
                ))
        return snapshots

    def _source_manifest(self, versions: list[ScriptFileVersion]) -> list[dict[str, Any]]:
        result = []
        for version in versions:
            script = self.db.get(ScriptFile, version.script_file_id)
            result.append({
                "script_file_id": script.id if script else version.script_file_id,
                "version_id": version.id,
                "version_no": version.version_no,
                "relative_path": script.relative_path if script else None,
                "file_hash": version.file_hash,
                "normalized_hash": version.normalized_hash,
                "git_commit_sha": version.git_commit_sha,
                "parse_status": version.parse_status,
                "enabled": bool(script.enabled) if script else True,
            })
        return sorted(result, key=lambda item: (int(item["script_file_id"]), int(item["version_no"])))

    @staticmethod
    def _warnings(versions: list[ScriptFileVersion], nodes: list[LineageNode], edges: list[LineageEdge]) -> list[str]:
        warnings = [
            f"脚本版本 {version.id} 解析状态为 {version.parse_status}，当前血缘版本需要审核"
            for version in versions if version.parse_status in _PARSE_WARNING_STATUSES
        ]
        if versions and not nodes and not edges:
            warnings.append("当前脚本版本未生成可用血缘节点或边")
        return warnings

    def _supersede_previous(self, revision: LineageRevision) -> None:
        rows = self.db.scalars(select(LineageRevision).where(
            LineageRevision.project_id == revision.project_id,
            LineageRevision.status == "published",
            LineageRevision.id != revision.id,
        )).all()
        for row in rows:
            row.status = "superseded"

def _match_renamed_nodes(
    old_nodes: dict[str, dict[str, Any]],
    new_nodes: dict[str, dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any], float]], set[str], set[str]]:
    """Pair removed/added nodes that are the same column under a new name.

    Matching is one-to-one and greedy on the highest similarity score, so a
    single rename produces exactly one pair.  Both sides must agree on node
    type and table name and clear ``_RENAME_SIMILARITY_THRESHOLD``; everything
    else is returned as an ordinary removal or addition.
    """

    removed_keys = [key for key in old_nodes if key not in new_nodes]
    added_keys = [key for key in new_nodes if key not in old_nodes]
    candidates: list[tuple[float, str, str]] = []
    for old_key in removed_keys:
        old = old_nodes[old_key]
        old_column = _normal(old.get("column_name"))
        if not old_column:
            continue
        for new_key in added_keys:
            new = new_nodes[new_key]
            if _normal(old.get("node_type")) != _normal(new.get("node_type")):
                continue
            if _normal(old.get("table_name")) != _normal(new.get("table_name")):
                continue
            ratio = SequenceMatcher(None, old_column, _normal(new.get("column_name"))).ratio()
            if ratio >= _RENAME_SIMILARITY_THRESHOLD:
                candidates.append((ratio, old_key, new_key))
    candidates.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    matched_old: set[str] = set()
    matched_new: set[str] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for ratio, old_key, new_key in candidates:
        if old_key in matched_old or new_key in matched_new:
            continue
        matched_old.add(old_key)
        matched_new.add(new_key)
        pairs.append((old_nodes[old_key], new_nodes[new_key], ratio))
    unmatched_removed = {key for key in removed_keys if key not in matched_old}
    unmatched_added = {key for key in added_keys if key not in matched_new}
    return pairs, unmatched_removed, unmatched_added


def _node_key(node: LineageNode) -> str:
    canonical = next((
        f"target_field:{node.target_field_id}" for _ in [0] if node.target_field_id
    ), None) or next((
        f"mart_field:{node.mart_field_id}" for _ in [0] if node.mart_field_id
    ), None) or next((
        f"source_field:{node.source_field_id}" for _ in [0] if node.source_field_id
    ), None) or next((
        f"catalog_column:{node.catalog_column_id}" for _ in [0] if node.catalog_column_id
    ), None)
    identity = {
        "canonical": canonical,
        "node_type": _normal(node.node_type),
        "database_name": _normal(node.database_name),
        "schema_name": _normal(node.schema_name),
        "table_name": _normal(node.table_name),
        "column_name": _normal(node.column_name),
        "logical_name": _normal(node.logical_name),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _node_snapshot(node: LineageNode, node_key: str, resolver: AssetDisplayResolver) -> dict[str, Any]:
    return {
        "id": node.id,
        "lineage_node_id": node.id,
        "node_key": node_key,
        "node_type": node.node_type,
        "logical_name": node.logical_name,
        "database_name": node.database_name,
        "schema_name": node.schema_name,
        "table_name": node.table_name,
        "column_name": node.column_name,
        "catalog_table_id": node.catalog_table_id,
        "catalog_column_id": node.catalog_column_id,
        "source_table_id": node.source_table_id,
        "source_field_id": node.source_field_id,
        "mart_table_id": node.mart_table_id,
        "mart_field_id": node.mart_field_id,
        "target_table_id": node.target_table_id,
        "target_field_id": node.target_field_id,
        "script_file_id": node.script_file_id,
        "script_file_version_id": node.script_file_version_id,
        "unresolved_flag": bool(node.unresolved_flag),
        "metadata": node.metadata_json or {},
        "display": resolver.describe_lineage_node(node),
    }


def _edge_snapshot(
    edge: LineageEdge,
    edge_key: str,
    source_key: str,
    target_key: str,
    source_node_id: int,
    target_node_id: int,
) -> dict[str, Any]:
    return {
        "id": edge.id,
        "lineage_edge_id": edge.id,
        "edge_key": edge_key,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "source_node_key": source_key,
        "target_node_key": target_key,
        "script_file_version_id": edge.script_file_version_id,
        "statement_id": edge.statement_id,
        "edge_type": edge.edge_type,
        "transformation_type": edge.transformation_type,
        "transformation_expression": edge.transformation_expression,
        "join_condition": edge.join_condition,
        "filter_condition": edge.filter_condition,
        "aggregation_rule": edge.aggregation_rule,
        "code_mapping_rule": edge.code_mapping_rule,
        "source_line_start": edge.source_line_start,
        "source_line_end": edge.source_line_end,
        "confidence_level": edge.confidence_level,
        "evidence": edge.evidence_json or {},
        "enabled": bool(edge.enabled),
    }


def _semantic_node(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key) for key in (
            "node_key", "node_type", "logical_name", "database_name", "schema_name",
            "table_name", "column_name", "catalog_table_id", "catalog_column_id",
            "source_table_id", "source_field_id", "mart_table_id", "mart_field_id",
            "target_table_id", "target_field_id", "unresolved_flag",
        )
    }


def _semantic_edge(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key) for key in (
            "edge_key", "source_node_key", "target_node_key", "edge_type", "transformation_type",
            "transformation_expression", "join_condition", "filter_condition", "aggregation_rule",
            "code_mapping_rule", "confidence_level", "enabled",
        )
    }


def _edge_change_category(fields: list[str]) -> tuple[str, str]:
    if "join_condition" in fields:
        return "join_changed", "high"
    if "filter_condition" in fields:
        return "filter_changed", "high"
    if "aggregation_rule" in fields:
        return "aggregation_changed", "high"
    if "code_mapping_rule" in fields:
        return "code_mapping_changed", "high"
    if "transformation_expression" in fields or "transformation_type" in fields:
        return "transformation_changed", "high"
    return "edge_changed", "medium"


def _diff_item(category: str, entity_type: str, old_value: dict[str, Any], new_value: dict[str, Any], severity: str, changed_fields: list[str] | None = None) -> dict[str, Any]:
    result = {
        "change_category": category,
        "entity_type": entity_type,
        "old_value": _safe_json(old_value),
        "new_value": _safe_json(new_value),
        "severity": severity,
    }
    if changed_fields:
        result["changed_fields"] = changed_fields
    return result


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items() if key not in {"metadata"} or isinstance(item, (dict, list, str, int, float, bool, type(None)))}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    return value


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normal(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _edge_sort_key(edge: LineageEdge) -> tuple[str, str, str, str, str]:
    return (
        _normal(edge.edge_type), _normal(edge.transformation_expression), _normal(edge.join_condition),
        _normal(edge.filter_condition), _normal(edge.aggregation_rule),
    )


__all__ = ["LineageRevisionService", "RevisionBuildResult", "PARSER_VERSION"]
