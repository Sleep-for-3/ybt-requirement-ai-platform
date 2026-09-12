"""Build and persist deterministic structured requirement snapshots.

The snapshot service deliberately sits between the existing requirement
workspace projection and future lineage/path resolution.  It does not invent
tables, fields, joins, or regulatory facts: unresolved values remain explicit
and are surfaced as reviewable recommendations.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn,
    CatalogTable,
    LineageEdge,
    LineageRevision,
    MappingEvidenceReference,
    MappingVersion,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    SourceToMartMapping,
    SourceTable,
    StructuredRequirementSnapshot,
    TargetField,
    TargetTable,
)
from app.services.deliverables.lineage_records import build_change_impact_records, build_lineage_records
from app.services.governance.audit import redact_summary
from app.services.asset_display import AssetDisplayResolver
from app.services.lineage.join_plan import JoinPlanStructurer, is_temporal_name
from app.services.lineage.path_resolver import LineagePathNotFound, LineagePathResolver
from app.services.requirement_workspace_projection import RequirementWorkspaceProjectionService


SNAPSHOT_SCHEMA_VERSION = "structured-requirement-v1"
SNAPSHOT_MODEL_VERSION = "requirement-workspace-v2"
PLAN_SCHEMA_VERSION = "requirement-field-plan-v1"
_MAX_CREATE_RETRIES = 5
# Path resolution is a per-field graph walk.  Keep it bounded so a large
# regulatory target table cannot turn one snapshot freeze into an N-field
# unbounded traversal; anything beyond the budget is reported as truncated.
MAX_PATH_FIELDS = 20
MAX_PATH_DEPTH = 10
MAX_PATHS_PER_FIELD = 3
MAX_HOPS_PER_PATH = 12
MAX_COMPACT_EVIDENCE = 5
_DICTIONARY_TABLE = re.compile(
    r"(?:^|_)(?:dim|dict|code|ref|lookup|map)(?:_|$)|字典|码表|码值表|参照表",
    re.IGNORECASE,
)


class RequirementSnapshotService:
    """Create immutable snapshots from governed project facts."""

    def __init__(self, db: Session):
        self.db = db
        # ``(table, column) -> exists?`` for the "source field is not in the
        # catalog" gap.  Scoped to one service instance so a snapshot freeze
        # does not repeat the same metadata lookup per field.
        self._catalog_column_cache: dict[tuple[int, str, str], bool] = {}

    def create(
        self,
        *,
        project_id: int,
        target_table_id: int,
        scenario_id: int | None,
        created_by: int | None,
        change_note: str | None = None,
    ) -> tuple[StructuredRequirementSnapshot, bool]:
        project, table, scenario = self._scope(project_id, target_table_id, scenario_id)
        scope_key = _scope_key(project_id, target_table_id, scenario.id if scenario else None)
        projection = RequirementWorkspaceProjectionService(self.db).projection(
            project_id,
            target_table_id,
            scenario.id if scenario else None,
        )
        catalog_revision = self._catalog_revision(project_id)
        lineage_revision = self._lineage_revision(project_id)
        content = self._build_content(
            project=project,
            table=table,
            scenario=scenario,
            projection=projection,
            catalog_revision=catalog_revision,
            lineage_revision=lineage_revision,
        )
        # Redact before hashing so the persisted representation and its
        # idempotency key are exactly the same safe, replayable payload.
        content = _sanitize_snapshot_content(content)
        content_hash = _content_hash(content)

        # A MAX()+1 read is only a candidate under concurrency.  The
        # non-null scope_key unique constraints are the final arbiter; a
        # savepoint lets us retry without poisoning the caller transaction.
        for _attempt in range(_MAX_CREATE_RETRIES):
            existing = self._existing_by_hash(scope_key, content_hash)
            if existing is not None:
                return existing, True
            snapshot_no = self._next_snapshot_no(scope_key)
            requirement_version = f"req-{snapshot_no}"
            versioned_content = {
                **content,
                "versions": {
                    **(content.get("versions") or {}),
                    "requirement_version": requirement_version,
                    "snapshot_no": snapshot_no,
                },
            }
            row = StructuredRequirementSnapshot(
                institution_id=project.institution_id,
                project_id=project_id,
                target_table_id=target_table_id,
                scenario_id=scenario.id if scenario else None,
                scope_key=scope_key,
                snapshot_no=snapshot_no,
                requirement_version=requirement_version,
                schema_version=SNAPSHOT_SCHEMA_VERSION,
                model_version=SNAPSHOT_MODEL_VERSION,
                catalog_revision=catalog_revision,
                lineage_revision=lineage_revision,
                status="draft",
                content_hash=content_hash,
                content_snapshot_json=_json_safe(versioned_content),
                change_note=change_note,
                created_by=created_by,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(row)
                    self.db.flush()
            except IntegrityError:
                # Another request may have inserted the same content or
                # consumed this version number.  Re-read the hash first;
                # otherwise recompute MAX()+1 and retry.
                existing = self._existing_by_hash(scope_key, content_hash)
                if existing is not None:
                    return existing, True
                continue
            return row, False
        raise RuntimeError("Unable to allocate a requirement snapshot version after concurrent retries")

    def _existing_by_hash(self, scope_key: str, content_hash: str) -> StructuredRequirementSnapshot | None:
        return self.db.scalar(select(StructuredRequirementSnapshot).where(
            StructuredRequirementSnapshot.scope_key == scope_key,
            StructuredRequirementSnapshot.content_hash == content_hash,
        ).order_by(StructuredRequirementSnapshot.id.desc()).limit(1))

    def _next_snapshot_no(self, scope_key: str) -> int:
        current = self.db.scalar(select(func.max(StructuredRequirementSnapshot.snapshot_no)).where(
            StructuredRequirementSnapshot.scope_key == scope_key,
        ))
        return int(current or 0) + 1

    def list(
        self,
        *,
        project_id: int,
        target_table_id: int | None = None,
        scenario_id: int | None = None,
        limit: int = 50,
    ) -> list[StructuredRequirementSnapshot]:
        query = select(StructuredRequirementSnapshot).where(
            StructuredRequirementSnapshot.project_id == project_id,
        )
        if target_table_id is not None:
            query = query.where(StructuredRequirementSnapshot.target_table_id == target_table_id)
        if scenario_id is not None:
            query = query.where(StructuredRequirementSnapshot.scenario_id == scenario_id)
        return list(self.db.scalars(query.order_by(StructuredRequirementSnapshot.id.desc()).limit(min(max(limit, 1), 200))).all())

    def get(self, *, project_id: int, snapshot_id: int) -> StructuredRequirementSnapshot:
        row = self.db.scalar(select(StructuredRequirementSnapshot).where(
            StructuredRequirementSnapshot.id == snapshot_id,
            StructuredRequirementSnapshot.project_id == project_id,
        ))
        if row is None:
            raise LookupError("Requirement snapshot not found")
        return row

    def _scope(self, project_id: int, target_table_id: int, scenario_id: int | None) -> tuple[Project, TargetTable, ProductScenario | None]:
        project = self.db.get(Project, project_id)
        if project is None:
            raise LookupError("Project not found")
        table = self.db.scalar(select(TargetTable).where(
            TargetTable.id == target_table_id,
            TargetTable.project_id == project_id,
        ))
        if table is None:
            raise LookupError("Target table does not belong to project")
        if scenario_id is None:
            scenario = self.db.scalar(select(ProductScenario).where(
                ProductScenario.project_id == project_id,
                ProductScenario.enabled.is_(True),
            ).order_by(ProductScenario.sort_order, ProductScenario.id).limit(1))
        else:
            scenario = self.db.scalar(select(ProductScenario).where(
                ProductScenario.id == scenario_id,
                ProductScenario.project_id == project_id,
            ))
            if scenario is None:
                raise LookupError("Scenario does not belong to project")
        return project, table, scenario

    def _build_content(
        self,
        *,
        project: Project,
        table: TargetTable,
        scenario: ProductScenario | None,
        projection: dict[str, Any],
        catalog_revision: str,
        lineage_revision: str,
    ) -> dict[str, Any]:
        field_ids = [int(item["field"]["id"]) for item in projection.get("records", [])]
        business_rows = self._rows_by_field(ScenarioBusinessMapping, project.id, field_ids, scenario.id if scenario else None)
        technical_rows = self._rows_by_field(ScenarioTechnicalLineage, project.id, field_ids, scenario.id if scenario else None)
        mart_rows = self._rows_by_field(MartToYbtMapping, project.id, field_ids, None)
        mart_field_ids = {row.mart_field_id for rows in mart_rows.values() for row in rows if row.mart_field_id}
        source_rows = self._source_rows(project.id, mart_field_ids)
        mart_fields = {
            row.id: row
            for row in self.db.scalars(select(MartField).where(
                MartField.project_id == project.id,
                MartField.id.in_(mart_field_ids),
            )).all()
        } if mart_field_ids else {}
        mart_table_ids = {row.mart_table_id for row in mart_fields.values()}
        mart_tables = {
            row.id: row
            for row in self.db.scalars(select(MartTable).where(
                MartTable.project_id == project.id,
                MartTable.id.in_(mart_table_ids),
            )).all()
        } if mart_table_ids else {}
        mapping_refs = self._evidence_refs(project.id, business_rows, technical_rows, mart_rows, source_rows)
        mapping_versions = self._mapping_versions(project.id, business_rows, technical_rows, mart_rows, source_rows)
        semantic_references = self._semantic_references(
            project.id,
            target_table_id=table.id,
            target_field_ids=field_ids,
            scenario_business_rows=business_rows,
            scenario_technical_rows=technical_rows,
            mart_rows=mart_rows,
        )
        target_fields = {
            row.id: row
            for row in self.db.scalars(select(TargetField).where(
                TargetField.project_id == project.id,
                TargetField.target_table_id == table.id,
            ).order_by(TargetField.id)).all()
        }

        field_plans: list[dict[str, Any]] = []
        join_structurer = JoinPlanStructurer(self.db, project.id)
        project_facts = self._project_facts(project.id)
        path_evidence = self._path_evidence(project.id, field_ids)
        for record in projection.get("records", []):
            field_id = int(record["field"]["id"])
            field = target_fields.get(field_id)
            if field is None:
                continue
            mart_for_field = mart_rows.get(field_id, [])
            source_for_field = [
                source
                for mart in mart_for_field
                if mart.mart_field_id
                for source in source_rows.get(mart.mart_field_id, [])
            ]
            field_plans.append(self._field_plan(
                field=field,
                table=table,
                scenario=scenario,
                business=business_rows.get(field_id, []),
                technical=technical_rows.get(field_id, []),
                mart_mappings=mart_for_field,
                source_mappings=source_for_field,
                mart_fields=mart_fields,
                mart_tables=mart_tables,
                evidence_refs=mapping_refs,
                mapping_versions=mapping_versions,
                readiness=record.get("readiness_status"),
                join_structurer=join_structurer,
                project_facts=project_facts,
                path_evidence=path_evidence["per_field"].get(field_id) or {
                    "paths": [],
                    "gaps": [],
                    "resolution": {"resolved": False, "reason": "outside_path_budget"},
                },
            ))

        warnings: list[str] = []
        if not self._has_current_lineage(project.id):
            warnings.append("当前项目没有可用于正式血缘版本的脚本边")
        elif not self._published_lineage_revision(project.id):
            warnings.append("当前项目尚无已发布的正式血缘版本，快照暂使用 derived 标识")
        if any(item.get("unresolved") for item in self._lineage_summary(project.id, table.id)):
            warnings.append("存在未解析的技术血缘节点，需人工确认")
        if path_evidence["truncated"]:
            warnings.append(
                f"监管字段超过 {MAX_PATH_FIELDS} 个，仅对前 {MAX_PATH_FIELDS} 个字段解析端到端路径，其余标记为未解析"
            )

        return _json_safe({
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_type": "structured_requirement",
            "scope": {
                "project_id": project.id,
                "project_name": project.name,
                "target_table_id": table.id,
                "target_table_code": table.table_code,
                "target_table_name": table.table_name,
                "scenario_id": scenario.id if scenario else None,
                "scenario_code": scenario.scenario_code if scenario else None,
                "scenario_name": scenario.scenario_name if scenario else None,
            },
            "versions": {
                "catalog_revision": catalog_revision,
                "lineage_revision": lineage_revision,
                "model_version": SNAPSHOT_MODEL_VERSION,
            },
            "target_table": {
                "id": table.id,
                "table_code": table.table_code,
                "business_name": table.table_name,
                "technical_name": table.table_code,
                "comment": table.description,
            },
            "plan_schema_version": PLAN_SCHEMA_VERSION,
            "field_plans": field_plans,
            "plan_summary": _plan_summary(field_plans, path_evidence),
            "path_resolution": {
                "max_fields": path_evidence["max_fields"],
                "field_count": path_evidence["field_count"],
                "resolved_fields": path_evidence["resolved_fields"],
                "truncated": path_evidence["truncated"],
                "warnings": path_evidence["warnings"][:5],
            },
            "questions": projection.get("question_summaries", []),
            "asset_summary": projection.get("asset_summary", {}),
            "readiness_summary": projection.get("readiness_summary", {}),
            "semantic_references": semantic_references,
            "lineage_records": self._lineage_summary(project.id, table.id),
            "change_impact_records": build_change_impact_records(self.db, project.id, table.id),
            "performance_budget": projection.get("performance_budget", {}),
            "warnings": warnings,
        })

    def _semantic_references(
        self,
        project_id: int,
        *,
        target_table_id: int,
        target_field_ids: list[int],
        scenario_business_rows: dict[int, list[Any]],
        scenario_technical_rows: dict[int, list[Any]],
        mart_rows: dict[int, list[Any]],
    ) -> dict[str, Any]:
        """Project read-only semantic references into the snapshot.

        SemanticConcept, SemanticConceptVersion and SemanticBinding remain the
        authoritative source tables.  We intentionally retain IDs, labels,
        lifecycle state and version metadata only; definitions and relations
        are resolved from the semantic catalog when a user opens a detail
        view, avoiding a second mutable semantic store.
        """
        entity_refs: set[tuple[str, int]] = {("target_table", int(target_table_id))}
        entity_refs.update(("target_field", int(field_id)) for field_id in target_field_ids)
        for entity_type, groups in (
            ("scenario_business_mapping", scenario_business_rows),
            ("scenario_technical_lineage", scenario_technical_rows),
            ("mart_to_ybt_mapping", mart_rows),
        ):
            entity_refs.update((entity_type, int(row.id)) for rows in groups.values() for row in rows)

        if not entity_refs:
            return {"read_only": True, "bindings": [], "concepts": [], "versions": []}

        predicates: list[Any] = []
        for entity_type in sorted({kind for kind, _ in entity_refs}):
            ids = [entity_id for kind, entity_id in entity_refs if kind == entity_type]
            if ids:
                predicates.append(
                    (SemanticBinding.entity_type == entity_type)
                    & SemanticBinding.entity_id.in_(ids)
                )
        bindings = list(self.db.scalars(select(SemanticBinding).where(
            SemanticBinding.project_id == project_id,
            or_(*predicates),
        ).order_by(SemanticBinding.id)).all()) if predicates else []

        concept_ids = sorted({int(row.semantic_concept_id) for row in bindings})
        concepts = {
            int(row.id): row
            for row in self.db.scalars(select(SemanticConcept).where(
                SemanticConcept.project_id == project_id,
                SemanticConcept.id.in_(concept_ids),
            ).order_by(SemanticConcept.id)).all()
        } if concept_ids else {}

        latest_versions: dict[int, SemanticConceptVersion] = {}
        if concept_ids:
            rows = self.db.scalars(select(SemanticConceptVersion).where(
                SemanticConceptVersion.project_id == project_id,
                SemanticConceptVersion.semantic_concept_id.in_(concept_ids),
            ).order_by(
                SemanticConceptVersion.semantic_concept_id,
                SemanticConceptVersion.version_no.desc(),
                SemanticConceptVersion.id.desc(),
            )).all()
            for row in rows:
                latest_versions.setdefault(int(row.semantic_concept_id), row)

        return _json_safe({
            "read_only": True,
            "bindings": [
                {
                    "id": row.id,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "binding_type": row.binding_type,
                    "semantic_concept_id": row.semantic_concept_id,
                    "confidence_level": row.confidence_level,
                    "confidence_score": row.confidence_score,
                    "status": row.status,
                    "source_type": row.source_type,
                    "source_id": row.source_id,
                }
                for row in bindings
                if row.semantic_concept_id in concepts
            ],
            "concepts": [
                {
                    "id": row.id,
                    "concept_type": row.concept_type,
                    "concept_code": row.concept_code,
                    "concept_name": row.concept_name,
                    "status": row.status,
                    "version": row.version,
                }
                for row in concepts.values()
            ],
            "versions": [
                {
                    "id": row.id,
                    "semantic_concept_id": row.semantic_concept_id,
                    "version_no": row.version_no,
                    "concept_name": row.concept_name,
                    "status": row.status,
                    "effective_from": row.effective_from,
                    "effective_to": row.effective_to,
                }
                for row in latest_versions.values()
            ],
        })

    def _field_plan(
        self,
        *,
        field: TargetField,
        table: TargetTable,
        scenario: ProductScenario | None,
        business: list[Any],
        technical: list[Any],
        mart_mappings: list[MartToYbtMapping],
        source_mappings: list[SourceToMartMapping],
        mart_fields: dict[int, MartField],
        mart_tables: dict[int, MartTable],
        evidence_refs: dict[tuple[str, int], list[dict[str, Any]]],
        mapping_versions: dict[tuple[str, int], dict[str, Any]],
        readiness: str | None,
        join_structurer: JoinPlanStructurer,
        project_facts: dict[str, Any],
        path_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target_asset = _asset(field, entity_type="target_field", layer_code="TARGET", table=table, db=self.db)
        joins: list[dict[str, Any]] = []
        transformations: list[dict[str, Any]] = []
        quality_rules: list[dict[str, Any]] = []
        for mapping in mart_mappings:
            mart_field = mart_fields.get(mapping.mart_field_id) if mapping.mart_field_id else None
            mart_table = mart_tables.get(mart_field.mart_table_id) if mart_field else None
            joins.append(join_structurer.structure(
                mapping_type="mart_to_ybt",
                mapping_id=mapping.id,
                raw_condition=mapping.join_condition,
                null_handling=mapping.null_handling_rule,
                left_hint=_asset(mart_field, entity_type="mart_field", layer_code="MART", table=mart_table, db=self.db)
                or _declared_hint(mapping.mart_table_summary, layer_code="MART", layer_name="监管集市"),
                right_hint=target_asset,
            ))
            transformations.append(_rule_set("mart_to_ybt", mapping.id, {
                "business_rule": mapping.business_rule,
                "filter_condition": mapping.filter_condition,
                "code_mapping_rule": mapping.code_mapping_rule,
                "null_handling_rule": mapping.null_handling_rule,
                "reporting_condition": mapping.reporting_condition,
            }))
            if mapping.validation_rule:
                quality_rules.append({"mapping_type": "mart_to_ybt", "mapping_id": mapping.id, "validation_rule": mapping.validation_rule})
        for mapping in source_mappings:
            mart_field = mart_fields.get(mapping.mart_field_id) if mapping.mart_field_id else None
            mart_table = mart_tables.get(mart_field.mart_table_id) if mart_field else None
            joins.append(join_structurer.structure(
                mapping_type="source_to_mart",
                mapping_id=mapping.id,
                raw_condition=mapping.join_condition,
                null_handling=mapping.null_handling_rule,
                left_hint=_declared_hint(mapping.source_tables_summary, layer_code="SOURCE", layer_name="源系统"),
                right_hint=_asset(mart_field, entity_type="mart_field", layer_code="MART", table=mart_table, db=self.db),
            ))
            transformations.append(_rule_set("source_to_mart", mapping.id, {
                "business_rule": mapping.business_rule,
                "filter_condition": mapping.filter_condition,
                "code_mapping_rule": mapping.code_mapping_rule,
                "priority_rule": mapping.priority_rule,
                "merge_rule": mapping.merge_rule,
                "null_handling_rule": mapping.null_handling_rule,
                "exception_rule": mapping.exception_rule,
            }))
            if mapping.quality_check_rule:
                quality_rules.append({"mapping_type": "source_to_mart", "mapping_id": mapping.id, "quality_check_rule": mapping.quality_check_rule})

        gaps = _dedupe_gaps([
            *self._gap_recommendations(
                field,
                business,
                technical,
                mart_mappings,
                source_mappings,
                joins=joins,
                project_facts=project_facts,
                evidence_refs=evidence_refs,
            ),
            *((path_evidence or {}).get("gaps") or []),
        ])
        mart_sources = []
        for mapping in mart_mappings:
            mart_field = mart_fields.get(mapping.mart_field_id) if mapping.mart_field_id else None
            mart_table = mart_tables.get(mart_field.mart_table_id) if mart_field else None
            mart_sources.append({
                "mapping_id": mapping.id,
                "mapping_name": mapping.mapping_name,
                "mapping_status": mapping.mapping_status,
                "mart_table_summary": mapping.mart_table_summary,
                "mart_field_summary": mapping.mart_field_summary,
                "mart_field": _asset(mart_field, entity_type="mart_field", layer_code="MART", table=mart_table, db=self.db),
                "rules": _rule_set("mart_to_ybt", mapping.id, {
                    "business_rule": mapping.business_rule,
                    "filter_condition": mapping.filter_condition,
                    "join_condition": mapping.join_condition,
                    "code_mapping_rule": mapping.code_mapping_rule,
                    "null_handling_rule": mapping.null_handling_rule,
                    "reporting_condition": mapping.reporting_condition,
                    "validation_rule": mapping.validation_rule,
                }),
                "open_questions": mapping.open_questions,
                "ai_generated_content": mapping.ai_generated_content,
                "final_content": mapping.final_content,
                "confidence_level": mapping.confidence_level,
                "created_by": mapping.created_by,
                "reviewed_by": mapping.reviewed_by,
                "reviewed_at": mapping.reviewed_at,
                "lineage_status": mapping.lineage_status,
                "lineage_last_verified_at": mapping.lineage_last_verified_at,
                "lineage_change_set_id": mapping.lineage_change_set_id,
                "version": mapping_versions.get(("mart_to_ybt", mapping.id)),
                "evidence": evidence_refs.get(("mart_to_ybt", mapping.id), []),
            })

        source_sources = [
            {
                "mapping_id": mapping.id,
                "mapping_name": mapping.mapping_name,
                "mapping_status": mapping.mapping_status,
                "mart_field_id": mapping.mart_field_id,
                "source_system_summary": mapping.source_system_summary,
                "source_tables_summary": mapping.source_tables_summary,
                "source_fields_summary": mapping.source_fields_summary,
                "rules": _rule_set("source_to_mart", mapping.id, {
                    "business_rule": mapping.business_rule,
                    "filter_condition": mapping.filter_condition,
                    "join_condition": mapping.join_condition,
                    "code_mapping_rule": mapping.code_mapping_rule,
                    "priority_rule": mapping.priority_rule,
                    "merge_rule": mapping.merge_rule,
                    "null_handling_rule": mapping.null_handling_rule,
                    "exception_rule": mapping.exception_rule,
                    "quality_check_rule": mapping.quality_check_rule,
                }),
                "open_questions": mapping.open_questions,
                "ai_generated_content": mapping.ai_generated_content,
                "final_content": mapping.final_content,
                "confidence_level": mapping.confidence_level,
                "created_by": mapping.created_by,
                "reviewed_by": mapping.reviewed_by,
                "reviewed_at": mapping.reviewed_at,
                "lineage_status": mapping.lineage_status,
                "lineage_last_verified_at": mapping.lineage_last_verified_at,
                "lineage_change_set_id": mapping.lineage_change_set_id,
                "version": mapping_versions.get(("source_to_mart", mapping.id)),
                "evidence": evidence_refs.get(("source_to_mart", mapping.id), []),
                "resolution_status": "summary_only",
            }
            for mapping in source_mappings
        ]

        return {
            "plan_version": PLAN_SCHEMA_VERSION,
            "target": target_asset,
            "target_field": target_asset,
            "scenario": {"id": scenario.id, "code": scenario.scenario_code, "name": scenario.scenario_name} if scenario else None,
            "business_requirements": [_business_payload(item, evidence_refs, mapping_versions) for item in business],
            "technical_lineage": [_technical_payload(item, evidence_refs, mapping_versions) for item in technical],
            "mart_sources": mart_sources,
            "source_sources": source_sources,
            "source_paths": list((path_evidence or {}).get("paths") or []),
            "path_resolution": (path_evidence or {}).get("resolution"),
            "join_plans": joins,
            "transformation_rules": transformations,
            "quality_rules": quality_rules,
            "evidence": [
                evidence
                for item in business + technical
                for evidence in evidence_refs.get(("scenario_business" if isinstance(item, ScenarioBusinessMapping) else "scenario_technical", item.id), [])
            ],
            "gap_recommendations": gaps,
            "gap_summary": _gap_summary(gaps),
            "requires_review": bool(gaps),
            "readiness_status": readiness or "incomplete",
        }

    def _rows_by_field(self, model, project_id: int, field_ids: list[int], scenario_id: int | None) -> dict[int, list[Any]]:
        result: dict[int, list[Any]] = defaultdict(list)
        if not field_ids:
            return result
        query = select(model).where(model.project_id == project_id, model.target_field_id.in_(field_ids))
        if hasattr(model, "scenario_id"):
            if scenario_id is None:
                return result
            query = query.where(model.scenario_id == scenario_id)
        for row in self.db.scalars(query.order_by(model.id)).all():
            result[row.target_field_id].append(row)
        return result

    def _source_rows(self, project_id: int, mart_field_ids: set[int]) -> dict[int, list[SourceToMartMapping]]:
        result: dict[int, list[SourceToMartMapping]] = defaultdict(list)
        if not mart_field_ids:
            return result
        for row in self.db.scalars(select(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project_id,
            SourceToMartMapping.mart_field_id.in_(mart_field_ids),
        ).order_by(SourceToMartMapping.id)).all():
            result[row.mart_field_id].append(row)
        return result

    def _evidence_refs(self, project_id: int, *groups: dict[int, list[Any]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
        typed_ids: set[tuple[str, int]] = set()
        for index, group in enumerate(groups):
            mapping_type = ("scenario_business", "scenario_technical", "mart_to_ybt", "source_to_mart")[index]
            typed_ids.update((mapping_type, row.id) for rows in group.values() for row in rows)
        if not typed_ids:
            return {}
        ids = {item[1] for item in typed_ids}
        rows = self.db.scalars(select(MappingEvidenceReference).where(
            MappingEvidenceReference.project_id == project_id,
            MappingEvidenceReference.mapping_id.in_(ids),
        ).order_by(MappingEvidenceReference.id)).all()
        result: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (row.mapping_type, row.mapping_id)
            if key not in typed_ids:
                continue
            result[key].append({
                "id": row.id,
                "evidence_type": row.evidence_type,
                "evidence_id": row.evidence_id,
                "source_name": row.source_name,
                "location_text": row.location_text,
                "evidence_summary": row.evidence_summary,
            })
        return result

    def _mapping_versions(self, project_id: int, *groups: dict[int, list[Any]]) -> dict[tuple[str, int], dict[str, Any]]:
        typed_ids: set[tuple[str, int]] = set()
        for index, group in enumerate(groups):
            mapping_type = ("scenario_business", "scenario_technical", "mart_to_ybt", "source_to_mart")[index]
            typed_ids.update((mapping_type, row.id) for rows in group.values() for row in rows)
        if not typed_ids:
            return {}
        ids = {item[1] for item in typed_ids}
        result: dict[tuple[str, int], dict[str, Any]] = {}
        for row in self.db.scalars(select(MappingVersion).where(
            MappingVersion.project_id == project_id,
            MappingVersion.mapping_id.in_(ids),
        ).order_by(
            MappingVersion.mapping_type,
            MappingVersion.mapping_id,
            MappingVersion.version_no.desc(),
            MappingVersion.created_at.desc(),
            MappingVersion.id.desc(),
        )).all():
            key = (row.mapping_type, row.mapping_id)
            if key in typed_ids and key not in result:
                result[key] = {"id": row.id, "version_no": row.version_no, "created_at": row.created_at}
        return result

    def _catalog_revision(self, project_id: int) -> str:
        tables = self.db.execute(select(
            CatalogTable.id,
            CatalogTable.metadata_hash,
            CatalogTable.enabled,
        ).where(CatalogTable.project_id == project_id).order_by(CatalogTable.id)).all()
        columns = self.db.execute(select(
            CatalogColumn.id,
            CatalogColumn.metadata_hash,
            CatalogColumn.enabled,
        ).where(CatalogColumn.project_id == project_id).order_by(CatalogColumn.id)).all()
        return "derived:" + _content_hash({
            "tables": [tuple(item) for item in tables],
            "columns": [tuple(item) for item in columns],
        })[:16]

    def _lineage_revision(self, project_id: int) -> str:
        published = self._published_lineage_revision(project_id)
        if published is not None:
            return f"revision:{published.id}:r{published.revision_no}"
        current_versions = self.db.execute(select(
            ScriptFileVersion.id,
            ScriptFileVersion.script_file_id,
            ScriptFileVersion.version_no,
            ScriptFileVersion.file_hash,
            ScriptFileVersion.normalized_hash,
            ScriptFileVersion.parse_status,
        ).join(ScriptFile, ScriptFile.id == ScriptFileVersion.script_file_id).where(
            ScriptFileVersion.project_id == project_id,
            ScriptFile.project_id == project_id,
            ScriptFileVersion.version_no == ScriptFile.current_version_no,
            ScriptFile.enabled.is_(True),
        ).order_by(ScriptFileVersion.id)).all()
        version_ids = [item.id for item in current_versions]
        edges = self.db.execute(select(
            LineageEdge.id,
            LineageEdge.script_file_version_id,
            LineageEdge.source_node_id,
            LineageEdge.target_node_id,
            LineageEdge.edge_type,
            LineageEdge.transformation_type,
            LineageEdge.join_condition,
            LineageEdge.filter_condition,
            LineageEdge.aggregation_rule,
            LineageEdge.code_mapping_rule,
            LineageEdge.enabled,
        ).where(
            LineageEdge.project_id == project_id,
            LineageEdge.enabled.is_(True),
            LineageEdge.script_file_version_id.in_(version_ids),
        ).order_by(LineageEdge.id)).all() if version_ids else []
        return "derived:" + _content_hash({
            "script_versions": [tuple(item) for item in current_versions],
            "edges": [tuple(item) for item in edges],
        })[:16]

    def _published_lineage_revision(self, project_id: int) -> LineageRevision | None:
        return self.db.scalar(select(LineageRevision).where(
            LineageRevision.project_id == project_id,
            LineageRevision.status == "published",
        ).order_by(LineageRevision.revision_no.desc()).limit(1))

    def _has_current_lineage(self, project_id: int) -> bool:
        return self.db.scalar(select(LineageEdge.id).where(
            LineageEdge.project_id == project_id,
            LineageEdge.enabled.is_(True),
        ).limit(1)) is not None

    def _lineage_summary(self, project_id: int, target_table_id: int) -> list[dict[str, Any]]:
        return _json_safe(build_lineage_records(self.db, project_id, target_table_id))

    def _project_facts(self, project_id: int) -> dict[str, Any]:
        """Project-level facts a gap recommendation may cite as evidence."""

        patterns = ("%字典%", "%码表%", "%码值%", "%参照表%", "%dict%", "%dim%", "%lookup%")
        dictionary_table_available = False
        for model in (CatalogTable, MartTable, SourceTable):
            clauses = []
            for attr in ("table_name", "table_code", "table_comment"):
                column = getattr(model, attr, None)
                if column is None:
                    continue
                clauses.extend(column.ilike(pattern) for pattern in patterns)
            if not clauses:
                continue
            hit = self.db.scalar(
                select(model.id).where(model.project_id == project_id, or_(*clauses)).limit(1)
            )
            if hit is not None:
                dictionary_table_available = True
                break
        return {"dictionary_table_available": dictionary_table_available}

    def _path_evidence(self, project_id: int, field_ids: list[int]) -> dict[str, Any]:
        """Resolve bounded end-to-end paths and path gaps for target fields."""

        revision = self._published_lineage_revision(project_id)
        selected = field_ids[:MAX_PATH_FIELDS]
        per_field: dict[int, dict[str, Any]] = {}
        warnings: list[str] = []
        for field_id in selected:
            try:
                payload = LineagePathResolver(self.db).resolve(
                    project_id,
                    root_entity_type="target_field",
                    root_entity_id=field_id,
                    direction="upstream",
                    depth=MAX_PATH_DEPTH,
                    lineage_revision_id=revision.id if revision is not None else None,
                    include_unresolved=True,
                    view="business",
                    max_paths=MAX_PATHS_PER_FIELD,
                )
            except LineagePathNotFound:
                per_field[field_id] = {
                    "paths": [],
                    "gaps": [],
                    "resolution": {"resolved": False, "reason": "root_not_in_scope"},
                }
                continue
            nodes = {node["id"]: node for node in payload.get("nodes", []) if isinstance(node, dict) and node.get("id")}
            edges = {edge["id"]: edge for edge in payload.get("edges", []) if isinstance(edge, dict) and edge.get("id")}
            raw_paths = list(payload.get("paths") or [])
            compact = [_compact_path(path, nodes, edges) for path in raw_paths[:MAX_PATHS_PER_FIELD]]
            per_field[field_id] = {
                "paths": compact,
                "gaps": _path_gaps(payload),
                "resolution": {
                    "resolved": True,
                    "revision_id": payload.get("revision_id"),
                    "path_count": len(raw_paths),
                    "complete_paths": sum(1 for path in compact if path["complete"]),
                    "unresolved_node_count": len(payload.get("unresolved_nodes") or []),
                    "confidence": payload.get("confidence"),
                    "truncated": bool(payload.get("truncated")) or any(path["truncated"] for path in compact),
                },
            }
            warnings.extend(payload.get("warnings") or [])
        return {
            "per_field": per_field,
            "truncated": len(field_ids) > MAX_PATH_FIELDS,
            "max_fields": MAX_PATH_FIELDS,
            "field_count": len(field_ids),
            "resolved_fields": len(per_field),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _gap_recommendations(
        self,
        field: TargetField,
        business: list[Any],
        technical: list[Any],
        mart_mappings: list[Any],
        source_mappings: list[Any],
        *,
        joins: list[dict[str, Any]] | None = None,
        project_facts: dict[str, Any] | None = None,
        evidence_refs: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        joins = joins or []
        facts = project_facts or {}
        evidence_refs = evidence_refs or {}
        gaps: list[dict[str, Any]] = []
        if not business:
            gaps.append(_gap(
                "business_mapping_missing",
                "缺少场景业务口径",
                "补充业务定义、统计口径和报送场景",
                field.id,
                "low",
                estimated_impact="需求文档缺少业务定义，开发无法确认取数口径",
            ))
        if not technical:
            gaps.append(_gap(
                "source_field_missing",
                "尚未找到可核验技术来源",
                "补充来源系统、表、字段和加工逻辑；如确无来源再评估新增字段或接口",
                field.id,
                "low",
                estimated_impact="需求文档无法给出可取数的来源字段",
            ))
        elif any(not (item.source_table_english_name and item.source_field_english_name) for item in technical):
            gaps.append(_gap(
                "source_field_incomplete",
                "技术溯源缺少物理表或字段",
                "补充可定位到目录或脚本行号的来源字段",
                field.id,
                "medium",
                estimated_impact="无法把需求精确到来源表和来源字段",
            ))
        elif not all(self._source_field_in_catalog(_declared_source(item), project_id=field.project_id) for item in technical):
            gaps.append(_gap(
                "source_field_not_in_catalog",
                "技术溯源引用的来源表字段未在项目目录中登记",
                "先同步源系统元数据确认字段是否存在；确认不存在时按建议新增字段流程提交，再回填映射",
                field.id,
                "low",
                rationale="项目目录中找不到匹配的目录列或已登记源字段，无法证明该来源字段真实存在",
                evidence_refs=[
                    evidence
                    for item in technical
                    for evidence in evidence_refs.get(("scenario_technical", item.id), [])
                ],
                estimated_impact="来源字段无法核验，需求文档可能要求开发取一个不存在的字段",
            ))
        if not mart_mappings:
            gaps.append(_gap(
                "mart_mapping_missing",
                "缺少监管集市到目标字段的映射",
                "建立监管集市字段映射；若监管集市不存在，提交新增集市字段或集市表评估（建议新增监管集市表）",
                field.id,
                "low",
                estimated_impact="缺少集市层，需求文档无法说明中间加工层级",
            ))
        if mart_mappings and not source_mappings:
            gaps.append(_gap(
                "source_to_mart_mapping_missing",
                "已有集市映射但没有来源映射",
                "补充源系统到监管集市的映射；无稳定关联键时再评估桥接表",
                field.id,
                "low",
                estimated_impact="无法回溯到源系统，端到端血缘存在断点",
            ))
        for mapping in [*mart_mappings, *source_mappings]:
            if not mapping.join_condition:
                gaps.append(_gap(
                    "join_condition_missing",
                    "关联条件未填写",
                    "确认左右表关联键、基数和时间对齐条件；不要在未确认前自动生成 Join",
                    field.id,
                    "medium",
                    mapping_id=mapping.id,
                    estimated_impact="开发无法写出可执行的关联条件",
                ))

        for plan in joins:
            mapping_id = plan.get("mapping_id")
            mapping_type = str(plan.get("mapping_type"))
            if plan.get("unresolved_references"):
                unresolved = [str(item) for item in plan["unresolved_references"]][:10]
                gaps.append(_gap(
                    "unresolved_join_key",
                    f"关联条件中有 {len(plan['unresolved_references'])} 处写法无法在项目内解析：" + "、".join(unresolved),
                    "确认左右表并补充统一业务主键或稳定的关联键，经人工审核后再写入需求文档",
                    field.id,
                    "medium",
                    mapping_id=mapping_id,
                    rationale="关联条件里的表或字段没有在本项目目录/集市/源系统中登记，无法证明关联成立",
                    evidence_refs=list(evidence_refs.get((mapping_type, int(mapping_id)), [])) if mapping_id else [],
                    affected_assets=_plan_affected_assets(field.id, plan),
                    estimated_impact="关联键无法确认，需求文档的取数逻辑不可执行",
                ))
            elif plan.get("structured") and plan.get("cardinality_basis") != "both_sides_declared":
                incomplete = plan.get("cardinality") == "unknown"
                gaps.append(_gap(
                    "missing_join_cardinality",
                    "关联键已解析，但缺少主键或唯一键证据，无法判定基数"
                    if incomplete
                    else "关联键已解析，但只确认了关联一侧的唯一性，另一侧未登记主键或唯一键",
                    "在元数据中登记主键或唯一键，或由业务确认一对一/一对多关系与数据粒度",
                    field.id,
                    "low",
                    mapping_id=mapping_id,
                    rationale="项目内没有该关联键的主键声明，无法证明关联基数与粒度",
                    evidence_refs=list(evidence_refs.get((mapping_type, int(mapping_id)), [])) if mapping_id else [],
                    estimated_impact="无法确认关联后行数是否放大，可能影响报送金额或户数准确性",
                ))

        declared_rules = [
            text
            for mapping in [*mart_mappings, *source_mappings]
            for text in (
                mapping.join_condition,
                mapping.filter_condition,
                getattr(mapping, "reporting_condition", None),
                mapping.business_rule,
            )
        ]
        if joins and not any(plan.get("time_conditions") for plan in joins) and not any(is_temporal_name(text) for text in declared_rules):
            gaps.append(_gap(
                "missing_time_field",
                "映射规则与关联条件中都没有出现统计日期、生效日期或账期对齐条件",
                "明确时间口径字段（统计日期/生效日期/快照日期）并在关联条件中登记",
                field.id,
                "low",
                estimated_impact="时间口径缺失会导致多期数据串档，需求文档无法说明取数期间",
            ))

        code_rules = [mapping.code_mapping_rule for mapping in [*mart_mappings, *source_mappings] if mapping.code_mapping_rule]
        if code_rules and not facts.get("dictionary_table_available"):
            gaps.append(_gap(
                "missing_dictionary_table",
                "存在码值转换规则，但项目内没有可引用的字典表或码表",
                "建立字典/码值表并在映射中引用，或在映射中登记完整的码值与业务含义对照",
                field.id,
                "low",
                rationale="码值转换目前只有文本规则，没有可追溯的字典资产",
                estimated_impact="码值口径无法复用，跨报表可能出现同名不同码",
            ))

        for mapping in source_mappings:
            declared = _split_declared_tables(mapping.source_tables_summary)
            plan = next((item for item in joins if item.get("mapping_type") == "source_to_mart" and item.get("mapping_id") == mapping.id), None)
            if len(declared) >= 2 and not (plan or {}).get("structured"):
                gaps.append(_gap(
                    "missing_bridge_table",
                    f"来源说明涉及 {len(declared)} 张表（{'、'.join(declared[:5])}），但没有已解析的关联键",
                    "补充桥接表并登记粒度与生效区间，或确认统一的业务主键后直接关联",
                    field.id,
                    "low",
                    mapping_id=mapping.id,
                    rationale="多表来源缺少可解析关联键，无法证明可以直接关联",
                    evidence_refs=list(evidence_refs.get(("source_to_mart", mapping.id), [])),
                    estimated_impact="多表拼接逻辑无法落地，开发可能需要自建中间表",
                ))
        return _dedupe_gaps(gaps)

    def _source_field_in_catalog(self, declared: dict[str, str] | None, *, project_id: int) -> bool:
        if not declared:
            return True
        table = declared["table"].strip().strip('"`[]').upper()
        column = declared["column"].strip().strip('"`[]').upper()
        if not table or not column:
            return True
        key = (project_id, table, column)
        if key in self._catalog_column_cache:
            return self._catalog_column_cache[key]
        catalog_hit = self.db.scalar(
            select(CatalogColumn.id)
            .where(
                CatalogColumn.project_id == project_id,
                func.upper(CatalogColumn.table_name) == table,
                func.upper(CatalogColumn.column_name) == column,
            )
            .limit(1)
        )
        source_hit = None
        if catalog_hit is None:
            source_hit = self.db.scalar(
                select(SourceField.id)
                .join(SourceTable, SourceTable.id == SourceField.source_table_id)
                .where(
                    SourceTable.project_id == project_id,
                    or_(
                        func.upper(SourceTable.table_code) == table,
                        func.upper(SourceTable.physical_table_name) == table,
                    ),
                    or_(
                        func.upper(SourceField.field_code) == column,
                        func.upper(SourceField.physical_column_name) == column,
                    ),
                )
                .limit(1)
            )
        exists = catalog_hit is not None or source_hit is not None
        self._catalog_column_cache[key] = exists
        return exists


def _asset(item: Any, *, entity_type: str, layer_code: str, table: Any | None = None, db: Session | None = None) -> dict[str, Any] | None:
    if item is None:
        return None
    if db is not None:
        resolved = AssetDisplayResolver(db).describe(entity_type, item)
        # Keep the snapshot's stable layer contract even if a legacy entity
        # has no explicit layer metadata.
        resolved["layer_code"] = resolved.get("layer_code") or layer_code
        return resolved
    if isinstance(item, TargetField):
        business_name = item.field_name or item.field_code
        comment = item.regulatory_refined_definition or item.regulatory_description or item.remarks or item.field_definition
        technical_name = item.field_code
        table_name = table.table_code if table else item.target_table_id
    elif isinstance(item, MartField):
        business_name = item.field_name or item.field_code
        comment = item.field_comment or item.description
        technical_name = item.physical_column_name or item.field_code
        table_name = table.physical_table_name if table and table.physical_table_name else (table.table_code if table else item.mart_table_id)
    else:
        business_name = getattr(item, "table_name", None) or getattr(item, "table_code", None)
        comment = getattr(item, "table_comment", None) or getattr(item, "description", None)
        technical_name = getattr(item, "physical_table_name", None) or getattr(item, "table_code", None)
        table_name = technical_name
    data_type = getattr(item, "field_type", None) or getattr(item, "data_type", None)
    required_flag = getattr(item, "required_flag", None)
    return {
        "id": item.id,
        "canonical_entity_id": item.id,
        "entity_type": entity_type,
        "display_name": business_name or "缺少业务备注",
        "business_name": business_name,
        "comment": comment,
        "aliases": [],
        "description": getattr(item, "description", None),
        "technical_name": technical_name,
        "technical_identifier": f"{table_name}.{technical_name}" if table_name and technical_name else technical_name,
        "qualified_technical_name": f"{table_name}.{technical_name}" if table_name and technical_name else technical_name,
        "display_name_source": "business_name" if business_name else "technical_name",
        "label_quality": "confirmed" if business_name and comment else ("available" if business_name else "missing"),
        "layer_code": layer_code,
        "layer_name": {"SOURCE": "源系统", "MART": "监管集市", "TARGET": "监管输出"}.get(layer_code, layer_code),
        "system_name": None,
        "data_type": data_type,
        "required_flag": required_flag,
    }


def _business_payload(item: ScenarioBusinessMapping, evidence_refs: dict[tuple[str, int], list[dict[str, Any]]], mapping_versions: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": item.id,
        "scenario_id": item.scenario_id,
        "status": item.business_confirm_status,
        "source_system_screenshot_required": item.source_system_screenshot_required,
        "source_system_change_required": item.source_system_change_required,
        "external_data_required": item.external_data_required,
        "manual_supplement_required": item.manual_supplement_required,
        "business_owner": item.business_owner,
        "business_confirm_at": item.business_confirm_at,
        "remarks": item.remarks,
        "confidence_level": item.confidence_level,
        "business_definition": item.business_definition,
        "final_content": item.final_content,
        "ai_generated_content": item.ai_generated_content,
        "open_questions": item.open_questions,
        "evidence": evidence_refs.get(("scenario_business", item.id), []),
        "version": mapping_versions.get(("scenario_business", item.id)),
    }


def _technical_payload(item: ScenarioTechnicalLineage, evidence_refs: dict[tuple[str, int], list[dict[str, Any]]], mapping_versions: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": item.id,
        "scenario_id": item.scenario_id,
        "business_mapping_id": item.business_mapping_id,
        "status": item.tech_confirm_status,
        "lineage_status": item.lineage_status,
        "confidence_level": item.confidence_level,
        "tech_owner": item.tech_owner,
        "tech_confirm_at": item.tech_confirm_at,
        "remarks": item.remarks,
        "lineage_last_verified_at": item.lineage_last_verified_at,
        "lineage_change_set_id": item.lineage_change_set_id,
        "source_system_name": item.source_system_name,
        "source_database_name": item.source_database_name,
        "source_schema_name": item.source_schema_name,
        "source_table_english_name": item.source_table_english_name,
        "source_table_chinese_name": item.source_table_chinese_name,
        "source_field_english_name": item.source_field_english_name,
        "source_field_chinese_name": item.source_field_chinese_name,
        "processing_logic_type": item.processing_logic_type,
        "processing_logic": item.processing_logic,
        "final_content": item.final_content,
        "ai_generated_content": item.ai_generated_content,
        "open_questions": item.open_questions,
        "evidence": evidence_refs.get(("scenario_technical", item.id), []),
        "version": mapping_versions.get(("scenario_technical", item.id)),
    }


def _declared_source(item: Any) -> dict[str, str] | None:
    table = (getattr(item, "source_table_english_name", None) or "").strip()
    column = (getattr(item, "source_field_english_name", None) or "").strip()
    if not table or not column:
        return None
    return {"table": table, "column": column}


def _split_declared_tables(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,，;；、\n\r\t]+", str(value)) if part.strip()]


def _gap_summary(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for gap in gaps:
        gap_type = str(gap.get("gap_type"))
        source = str(gap.get("source") or "requirement_snapshot")
        by_type[gap_type] = by_type.get(gap_type, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "total": len(gaps),
        "by_type": {key: by_type[key] for key in sorted(by_type)},
        "by_source": {key: by_source[key] for key in sorted(by_source)},
        "pending_review": sum(1 for gap in gaps if gap.get("approval_status") == "pending_review"),
    }


def _plan_summary(field_plans: list[dict[str, Any]], path_evidence: dict[str, Any]) -> dict[str, Any]:
    """Aggregate snapshot-level readiness without inventing a denominator."""

    join_plans = [
        plan
        for field in field_plans
        for plan in (field.get("join_plans") or [])
    ]
    structured_plans = [plan for plan in join_plans if plan.get("structured")]
    gaps = [
        gap
        for field in field_plans
        for gap in (field.get("gap_recommendations") or [])
    ]
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for gap in gaps:
        gap_type = str(gap.get("gap_type"))
        source = str(gap.get("source") or "requirement_snapshot")
        by_type[gap_type] = by_type.get(gap_type, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "field_plan_count": len(field_plans),
        "fields_with_gaps": sum(1 for field in field_plans if field.get("gap_recommendations")),
        "fields_with_complete_path": sum(
            1
            for field in field_plans
            if ((field.get("path_resolution") or {}).get("complete_paths") or 0) > 0
        ),
        "join_plan_count": len(join_plans),
        "structured_join_count": len(structured_plans),
        "structured_join_ratio": (len(structured_plans) / len(join_plans)) if join_plans else None,
        "gap_total": len(gaps),
        "gap_counts_by_type": {key: by_type[key] for key in sorted(by_type)},
        "gap_counts_by_source": {key: by_source[key] for key in sorted(by_source)},
        "fields_missing_business_comment": sum(
            1
            for field in field_plans
            if ((field.get("target") or {}).get("label_quality") == "missing")
        ),
        "path_resolution": {
            "max_fields": path_evidence.get("max_fields"),
            "field_count": path_evidence.get("field_count"),
            "resolved_fields": path_evidence.get("resolved_fields"),
            "truncated": bool(path_evidence.get("truncated")),
            "warnings": list(path_evidence.get("warnings") or [])[:5],
        },
    }


def _plan_affected_assets(field_id: int, plan: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = [{"entity_type": "target_field", "id": field_id}]
    mapping_id = plan.get("mapping_id")
    if mapping_id:
        assets.append({"entity_type": f"{plan.get('mapping_type')}_mapping", "id": int(mapping_id)})
    for side in ("left", "right"):
        entity_type = (plan.get(side) or {}).get("entity_type")
        entity_id = (plan.get(side) or {}).get("entity_id")
        if entity_type and entity_id:
            assets.append({"entity_type": entity_type, "id": int(entity_id)})
    return assets


def _compact_path(path: dict[str, Any], nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Project one resolved path into a business-readable, bounded summary."""

    node_ids = list(path.get("node_ids") or [])
    hops = []
    for node_id in node_ids[:MAX_HOPS_PER_PATH]:
        node = nodes.get(node_id)
        if node is None:
            continue
        display = node.get("display") or {}
        hops.append({
            "node_id": node_id,
            "entity_type": node.get("entity_type"),
            "entity_id": node.get("canonical_entity_id"),
            "layer_code": node.get("layer_code"),
            "layer_name": node.get("layer_name"),
            "display_name": display.get("display_name"),
            "business_name": display.get("business_name"),
            "comment": display.get("comment"),
            "technical_name": display.get("technical_name"),
            "label_quality": display.get("label_quality"),
            "unresolved_flag": bool(node.get("unresolved_flag")),
        })
    path_edges = [edges[edge_id] for edge_id in path.get("edge_ids", []) if edge_id in edges]
    transformations = [
        {
            "edge_id": edge["id"],
            "relation_source": edge.get("relation_source"),
            "mapping_type": edge.get("mapping_type"),
            "mapping_id": edge.get("mapping_id"),
            "transformation_type": edge.get("transformation_type"),
            "transformation_expression": edge.get("transformation_expression"),
            "join_condition": edge.get("join_condition"),
            "filter_condition": edge.get("filter_condition"),
            "aggregation_rule": edge.get("aggregation_rule"),
            "code_mapping_rule": edge.get("code_mapping_rule"),
            "source_line_start": edge.get("source_line_start"),
            "source_line_end": edge.get("source_line_end"),
            "confidence_level": edge.get("confidence_level"),
        }
        for edge in path_edges
        if any(edge.get(key) for key in (
            "transformation_expression", "join_condition", "filter_condition",
            "aggregation_rule", "code_mapping_rule",
        ))
    ][:MAX_HOPS_PER_PATH]
    return {
        "path_id": path.get("path_id"),
        "complete": bool(path.get("complete")),
        "confidence": path.get("confidence"),
        "hop_count": len(node_ids),
        "truncated": len(node_ids) > MAX_HOPS_PER_PATH,
        "hops": hops,
        "transformations": transformations,
        "unresolved_node_ids": list(path.get("unresolved_node_ids") or [])[:MAX_HOPS_PER_PATH],
        "evidence_refs": list(path.get("evidence_refs") or [])[:MAX_COMPACT_EVIDENCE],
    }


def _path_gaps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert resolver gaps into snapshot gaps with business-readable names."""

    nodes = {
        node["id"]: node
        for node in payload.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    result = []
    for gap in payload.get("gap_recommendations") or []:
        assets = []
        for reference in gap.get("affected_assets") or []:
            node = nodes.get(str(reference))
            display = (node or {}).get("display") or {}
            assets.append({
                "entity_type": (node or {}).get("entity_type") or "lineage_node",
                "id": (node or {}).get("canonical_entity_id"),
                "node_id": str(reference),
                "display_name": display.get("display_name"),
                "technical_name": display.get("technical_name"),
                "layer_name": (node or {}).get("layer_name"),
                "label_quality": display.get("label_quality"),
            })
        result.append({
            "gap_type": gap.get("gap_type"),
            "problem_statement": gap.get("problem_statement"),
            "recommended_change": gap.get("recommended_change"),
            "alternative_options": list(gap.get("alternative_options") or []),
            "rationale": gap.get("rationale"),
            "evidence_refs": list(gap.get("evidence_refs") or []),
            "affected_assets": assets,
            "estimated_impact": gap.get("estimated_impact"),
            "confidence_level": gap.get("confidence_level"),
            "approval_status": gap.get("approval_status") or "pending_review",
            "source": "lineage_path",
            "dedupe_key": _gap_key(
                str(gap.get("gap_type")),
                str(gap.get("problem_statement")),
                assets,
                "lineage_path",
            ),
        })
    return result


def _declared_hint(value: str | None, *, layer_code: str, layer_name: str) -> dict[str, Any] | None:
    """Describe a table that a mapping *declares* but the project has not bound.

    The hint is deliberately marked ``hint_quality="declared_text"`` so it can
    never be mistaken for a resolved catalog asset.
    """

    text = (value or "").strip()
    if not text:
        return None
    return {
        "id": None,
        "canonical_entity_id": None,
        "entity_type": "declared_table",
        "display_name": text[:500],
        "business_name": text[:500],
        "comment": None,
        "aliases": [],
        "description": None,
        "technical_name": text[:500],
        "technical_identifier": text[:500],
        "qualified_technical_name": text[:500],
        "display_name_source": "mapping_summary",
        "label_quality": "unresolved",
        "hint_quality": "declared_text",
        "layer_code": layer_code,
        "layer_name": layer_name,
        "system_name": None,
    }


def _rule_set(mapping_type: str, mapping_id: int, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping_type": mapping_type,
        "mapping_id": mapping_id,
        "rules": {key: value for key, value in values.items() if value not in (None, "")},
    }


_GAP_ALTERNATIVES: dict[str, list[str]] = {
    "unresolved_join_key": ["先由业务确认统一业务主键，再回填映射关联条件"],
    "missing_bridge_table": ["改用统一的业务主键直连", "补充桥接表并登记粒度与生效区间"],
    "missing_dictionary_table": ["在映射中登记码值与业务含义对照", "建立独立字典表并在映射中引用"],
    "missing_time_field": ["在映射中补充统计日期/生效日期的对齐条件", "在目标表中明确账期字段"],
    "missing_join_cardinality": ["在元数据中登记主键或唯一键", "由业务确认关联基数后回填"],
    "source_field_not_in_catalog": ["先同步源系统元数据，再确认字段是否存在", "由源系统新增字段后再绑定"],
    "missing_asset_binding": ["先在目录中登记该表/字段", "改用已登记且已审核的资产"],
    "missing_lineage_revision": ["先构建并发布项目级血缘版本"],
    "missing_technical_evidence": ["补充脚本运行版本与字段绑定证据"],
}


def _gap(
    gap_type: str,
    problem_statement: str,
    recommended_change: str,
    field_id: int,
    confidence_level: str,
    *,
    mapping_id: int | None = None,
    rationale: str | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    affected_assets: list[dict[str, Any]] | None = None,
    estimated_impact: str = "待人工评估",
    alternative_options: list[str] | None = None,
    source: str = "requirement_snapshot",
) -> dict[str, Any]:
    """Build one auditable gap recommendation.

    Gaps are *recommendations*: they always carry ``approval_status`` and must
    never be applied to production models automatically.
    """

    assets = affected_assets or [{"entity_type": "target_field", "id": field_id}]
    return {
        "gap_type": gap_type,
        "problem_statement": problem_statement,
        "recommended_change": recommended_change,
        "alternative_options": alternative_options if alternative_options is not None else _GAP_ALTERNATIVES.get(gap_type, []),
        "rationale": rationale or "基于当前项目已保存的字段、映射、血缘和证据；不是模型臆测",
        "evidence_refs": evidence_refs or [],
        "affected_assets": assets,
        "mapping_id": mapping_id,
        "estimated_impact": estimated_impact,
        "confidence_level": confidence_level,
        "approval_status": "pending_review",
        "source": source,
        "dedupe_key": _gap_key(gap_type, problem_statement, assets, source),
    }


def _gap_key(gap_type: str, problem_statement: str, assets: list[dict[str, Any]], source: str) -> str:
    asset_keys = sorted(
        f"{item.get('entity_type')}:{item.get('id')}" for item in assets if isinstance(item, dict)
    )
    return _content_hash([source, gap_type, problem_statement, asset_keys])[:32]


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for gap in gaps:
        key = gap.get("dedupe_key") or _gap_key(
            str(gap.get("gap_type")),
            str(gap.get("problem_statement")),
            list(gap.get("affected_assets") or []),
            str(gap.get("source")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append({**gap, "dedupe_key": key})
    return result


def _scope_key(project_id: int, target_table_id: int, scenario_id: int | None) -> str:
    """Return a stable, non-null key for a snapshot's logical scope."""
    return f"project:{int(project_id)}|target:{int(target_table_id)}|scenario:{int(scenario_id) if scenario_id is not None else 0}"


def _sanitize_snapshot_content(value: Any) -> Any:
    """Apply the platform's recursive secret/PII redaction policy.

    Snapshot content is intended for replay and document generation, so we
    keep business and technical identifiers while removing known secret-key
    payloads and masking credential/PII patterns before persistence and hash
    calculation.  Evidence quotations are never included by the builder.
    """
    return _json_safe(redact_summary(value))


def _content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
