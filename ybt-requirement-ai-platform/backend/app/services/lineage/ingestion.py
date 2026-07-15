from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ImpactAnalysis, LineageEdge, LineageNode, Project, ScriptChangeSet, ScriptDependency, ScriptFile, ScriptFileVersion, SqlStatement,
    StoredFile, TemplateVariable, User,
)
from app.services.lineage.preprocessing import preprocess_sql
from app.services.lineage.sql_parser import LineageNodeSpec, parse_sql_lineage
from app.services.lineage.shell_parser import parse_shell_dependencies
from app.services.lineage.resolver import resolve_lineage_node
from app.services.lineage.impact_analyzer import persist_change_impact
from app.services.lineage.version_diff import compare_shell_versions, compare_sql_versions
from app.services.storage.base import StorageService
from app.services.governance.audit import record_audit


ALLOWED_SCRIPT_EXTENSIONS = {".sql", ".sh", ".ksh", ".bash", ".txt"}


@dataclass(frozen=True)
class IngestionResult:
    script_file: ScriptFile
    version: ScriptFileVersion
    stored_file: StoredFile
    deduplicated: bool
    node_count: int
    edge_count: int
    change_set: ScriptChangeSet | None = None
    impact: ImpactAnalysis | None = None
    change_categories: tuple[str, ...] = ()


class ScriptIngestionService:
    """Deep module for safe script storage, versioning and static parsing."""

    def __init__(self, db: Session, storage: StorageService):
        self.db = db
        self.storage = storage

    def ingest(
        self,
        *,
        project: Project,
        data: bytes,
        file_name: str,
        relative_path: str | None,
        dialect: str | None,
        actor_user_id: int | None,
        code_repository_id: int | None = None,
        git_commit_sha: str | None = None,
        change_note: str | None = None,
    ) -> IngestionResult:
        safe_path = validate_script_path(relative_path or file_name)
        suffix = Path(file_name).suffix.lower()
        if suffix not in ALLOWED_SCRIPT_EXTENSIONS:
            raise ValueError(f"Unsupported script extension: {suffix or '<none>'}")
        if Path(file_name).name != file_name:
            raise ValueError("Invalid script file name")
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Scripts must use UTF-8 encoding") from exc
        actor_id = ensure_actor_user_id(self.db, actor_user_id)
        digest = hashlib.sha256(data).hexdigest()
        stored_file = self.db.scalar(select(StoredFile).where(
            StoredFile.institution_id == project.institution_id,
            StoredFile.project_id == project.id,
            StoredFile.content_hash == digest,
            StoredFile.enabled.is_(True),
        ))
        if stored_file is None:
            saved = self.storage.save(data, file_name=file_name, project_id=project.id)
            stored_file = StoredFile(
                institution_id=project.institution_id,
                project_id=project.id,
                storage_key=saved.storage_key,
                original_file_name=file_name,
                content_type="text/plain",
                byte_size=saved.byte_size,
                content_hash=saved.content_hash,
                classification=project.confidentiality_level,
                created_by=actor_id,
                enabled=True,
            )
            self.db.add(stored_file)
            self.db.flush()

        script_file = self.db.scalar(select(ScriptFile).where(
            ScriptFile.project_id == project.id,
            ScriptFile.code_repository_id.is_(None) if code_repository_id is None else ScriptFile.code_repository_id == code_repository_id,
            ScriptFile.relative_path == safe_path,
        ))
        if script_file is None:
            script_file = ScriptFile(
                institution_id=project.institution_id,
                project_id=project.id,
                code_repository_id=code_repository_id,
                relative_path=safe_path,
                file_name=file_name,
                file_type=_file_type(suffix),
                enabled=True,
                current_version_no=0,
            )
            self.db.add(script_file)
            self.db.flush()
        else:
            script_file.enabled = True
            script_file.file_name = file_name

        duplicate = self.db.scalar(select(ScriptFileVersion).where(
            ScriptFileVersion.script_file_id == script_file.id,
            ScriptFileVersion.file_hash == digest,
        ))
        if duplicate is not None:
            record_audit(
                self.db, action="duplicate_upload", resource_type="script_file_version", resource_id=duplicate.id,
                actor_user_id=actor_id, institution_id=project.institution_id, project_id=project.id,
                after={"script_file_id": script_file.id, "version_no": duplicate.version_no, "file_hash": digest},
            )
            self.db.commit()
            return IngestionResult(
                script_file, duplicate, stored_file, True,
                self._node_count(duplicate.id), self._edge_count(duplicate.id),
            )

        previous_version = self.db.scalar(select(ScriptFileVersion).where(
            ScriptFileVersion.script_file_id == script_file.id,
        ).order_by(ScriptFileVersion.version_no.desc()).limit(1))

        normalized = _semantic_text(content)
        version = ScriptFileVersion(
            project_id=project.id,
            script_file_id=script_file.id,
            version_no=script_file.current_version_no + 1,
            git_commit_sha=git_commit_sha,
            file_hash=digest,
            normalized_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            raw_content_storage_file_id=stored_file.id,
            parse_status="pending",
            dialect=dialect,
            change_note=change_note,
            warnings_json=[],
            created_by=actor_id,
        )
        self.db.add(version)
        self.db.flush()
        script_file.current_version_no = version.version_no
        if script_file.file_type == "sql":
            self._persist_sql(project, script_file, version, content, dialect or "")
        elif script_file.file_type == "shell":
            self._persist_shell(project, script_file, version, content)
        else:
            version.parse_status = "pending"
            version.warnings_json = ["Shell dependency parsing pending"]
        change_set = None
        impact = None
        categories: tuple[str, ...] = ()
        if previous_version is not None and script_file.file_type in {"sql", "shell"}:
            previous_stored = self.db.get(StoredFile, previous_version.raw_content_storage_file_id)
            if previous_stored is not None:
                previous_content = self.storage.read(previous_stored.storage_key).decode("utf-8-sig")
                diff = compare_sql_versions(previous_content, content, dialect=dialect or previous_version.dialect or "") if script_file.file_type == "sql" else compare_shell_versions(previous_content, content)
                change_set, impact = persist_change_impact(
                    self.db,
                    script_file=script_file,
                    from_version=previous_version,
                    to_version=version,
                    diff=diff,
                    created_by=actor_id,
                )
                categories = tuple(item.change_category for item in diff.items)
        record_audit(
            self.db, action="script_ingest", resource_type="script_file_version", resource_id=version.id,
            actor_user_id=actor_id, institution_id=project.institution_id, project_id=project.id,
            after={"script_file_id": script_file.id, "version_no": version.version_no, "file_hash": version.file_hash, "parse_status": version.parse_status, "change_set_id": change_set.id if change_set else None},
        )
        self.db.commit()
        self.db.refresh(version)
        return IngestionResult(script_file, version, stored_file, False, self._node_count(version.id), self._edge_count(version.id), change_set, impact, categories)

    def _persist_shell(self, project: Project, script_file: ScriptFile, version: ScriptFileVersion, content: str) -> None:
        result = parse_shell_dependencies(content)
        version.parse_status = "parsed" if not result.warnings else "partially_parsed"
        version.warnings_json = list(result.warnings)
        parent_dir = str(PurePosixPath(script_file.relative_path).parent)
        for item in result.dependencies:
            target = item.target_path or ""
            candidate_paths = [target]
            if parent_dir != ".":
                candidate_paths.append(str(PurePosixPath(parent_dir) / target))
            child = self.db.scalar(select(ScriptFile).where(
                ScriptFile.project_id == project.id,
                ScriptFile.relative_path.in_(candidate_paths),
                ScriptFile.enabled.is_(True),
            ).limit(1))
            if child is None and target:
                child = self.db.scalar(select(ScriptFile).where(
                    ScriptFile.project_id == project.id,
                    ScriptFile.file_name == PurePosixPath(target).name,
                    ScriptFile.enabled.is_(True),
                ).limit(1))
            self.db.add(ScriptDependency(
                project_id=project.id,
                parent_script_file_id=script_file.id,
                child_script_file_id=child.id if child else None,
                dependency_type=item.dependency_type,
                call_expression=item.call_expression,
                condition_expression=item.condition_expression,
                source_line_start=item.source_line_start,
                source_line_end=item.source_line_end,
                confidence_level=item.confidence_level,
                warnings_json=list(item.warnings) + ([] if child else [f"Unresolved target: {target}"]),
            ))
        self.db.flush()

    def _persist_sql(self, project: Project, script_file: ScriptFile, version: ScriptFileVersion, content: str, dialect: str) -> None:
        configured = {
            item.variable_name: item.example_value
            for item in self.db.scalars(select(TemplateVariable).where(
                TemplateVariable.project_id == project.id,
                TemplateVariable.confirmed.is_(True),
            )).all()
            if item.example_value
        }
        result = parse_sql_lineage(content, dialect=dialect, variables=configured)
        version.parse_status = result.parse_status
        version.warnings_json = list(result.warnings)
        statement_rows: dict[int, SqlStatement] = {}
        for item in result.statements:
            row = SqlStatement(
                project_id=project.id,
                script_file_version_id=version.id,
                statement_index=item.statement_index,
                statement_type=item.statement_type,
                raw_sql_hash=item.raw_sql_hash,
                normalized_sql=item.normalized_sql,
                dialect=dialect or None,
                parse_status=item.parse_status,
                source_line_start=item.source_line_start,
                source_line_end=item.source_line_end,
                warnings_json=list(item.warnings),
            )
            self.db.add(row)
            self.db.flush()
            statement_rows[item.statement_index] = row
        node_rows: dict[tuple[str, str], LineageNode] = {}

        def node_for(spec: LineageNodeSpec) -> LineageNode:
            key = (spec.node_type, spec.logical_name)
            if key not in node_rows:
                row = LineageNode(
                    institution_id=project.institution_id,
                    project_id=project.id,
                    node_type=spec.node_type,
                    logical_name=spec.logical_name,
                    database_name=spec.database_name,
                    schema_name=spec.schema_name,
                    table_name=spec.table_name,
                    column_name=spec.column_name,
                    script_file_id=script_file.id,
                    script_file_version_id=version.id,
                    temporary_flag=spec.temporary_flag,
                    unresolved_flag=spec.unresolved_flag,
                    metadata_json=spec.metadata,
                )
                self.db.add(row)
                self.db.flush()
                node_rows[key] = row
            return node_rows[key]

        for spec in result.nodes:
            node_for(spec)
        for item in result.edges:
            statement_index = int(item.evidence.get("statement_index", 0))
            statement = statement_rows.get(statement_index)
            self.db.add(LineageEdge(
                institution_id=project.institution_id,
                project_id=project.id,
                script_file_version_id=version.id,
                statement_id=statement.id if statement else None,
                source_node_id=node_for(item.source).id,
                target_node_id=node_for(item.target).id,
                edge_type=item.edge_type,
                transformation_type=item.transformation_type,
                transformation_expression=item.transformation_expression,
                join_condition=item.join_condition,
                filter_condition=item.filter_condition,
                aggregation_rule=item.aggregation_rule,
                code_mapping_rule=item.code_mapping_rule,
                source_line_start=statement.source_line_start if statement else None,
                source_line_end=statement.source_line_end if statement else None,
                confidence_level=item.confidence_level,
                evidence_json=item.evidence,
                enabled=True,
            ))
        for row in node_rows.values():
            if row.node_type in {"table", "temporary_table", "column"}:
                resolve_lineage_node(self.db, row)
        self.db.flush()

    def _node_count(self, version_id: int) -> int:
        return len(self.db.scalars(select(LineageNode.id).where(LineageNode.script_file_version_id == version_id)).all())

    def _edge_count(self, version_id: int) -> int:
        return len(self.db.scalars(select(LineageEdge.id).where(LineageEdge.script_file_version_id == version_id)).all())


def validate_script_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid or unsafe script path")
    return str(path)


def _semantic_text(content: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", content, flags=re.S)
    without_lines = re.sub(r"(?m)^\s*(--|#).*?$", "", without_block)
    return re.sub(r"\s+", " ", without_lines).strip().lower()


def _file_type(suffix: str) -> str:
    return "sql" if suffix == ".sql" else "shell" if suffix in {".sh", ".ksh", ".bash"} else "text"


def ensure_actor_user_id(db: Session, actor_user_id: int | None) -> int:
    if actor_user_id is not None:
        return actor_user_id
    user = db.scalar(select(User).where(User.username == "legacy-system"))
    if user is None:
        user = User(username="legacy-system", display_name="Legacy system", status="active")
        db.add(user); db.flush()
    return user.id
