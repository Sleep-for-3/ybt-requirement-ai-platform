"""Store rendered requirement documents once per render identity (P1-A).

Design rules:

1. Rendering happens at most once per ``render_identity``.  A second request with
   the same identity returns the stored bytes instead of rendering again.
2. The identity separates storage concerns: content hash, template hash,
   renderer version, mapping config version, format and frozen source.  Changing
   any of them yields a new identity, a new row and a new file; old files are
   never overwritten (history stays readable).
3. Reads verify ``file_sha256``.  A tampered or missing file is an error, never a
   silent re-render — otherwise "download == approved file" would stop being true.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RequirementRenderArtifact
from app.services.storage.factory import get_storage_service

ARTIFACT_SCHEMA_VERSION = "render-artifact-v1"

#: Built-in exports have no customer template; the version pins the renderer code.
LEGACY_RENDERERS = {"docx": "builtin-docx-v1", "xlsx": "builtin-xlsx-v1"}

MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class RenderArtifactError(RuntimeError):
    """Raised when a stored artifact cannot be trusted or produced."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ArtifactRequest:
    project_id: int
    requirement_id: int
    source_kind: str
    source_id: int
    format: str
    file_name: str
    content_hash: str
    renderer_version: str
    config_version: str = ""
    config_digest: str = ""
    template_sha256: str = ""
    snapshot_hash: str | None = None
    media_type: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def render_identity(request: ArtifactRequest) -> str:
    """Hash everything that must be equal for two downloads to be the same file."""

    canonical = {
        "schema": ARTIFACT_SCHEMA_VERSION,
        "content_hash": request.content_hash,
        "template_sha256": request.template_sha256,
        "renderer_version": request.renderer_version,
        "config_version": request.config_version,
        "config_digest": request.config_digest,
        "format": request.format,
        "source_kind": request.source_kind,
        "source_id": request.source_id,
    }
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_artifact(db: Session, project_id: int, identity: str) -> RequirementRenderArtifact | None:
    return db.scalar(
        select(RequirementRenderArtifact).where(
            RequirementRenderArtifact.project_id == project_id,
            RequirementRenderArtifact.render_identity == identity,
        )
    )


def ensure_artifact(
    db: Session,
    request: ArtifactRequest,
    producer: Callable[[], bytes],
    *,
    created_by: int | None = None,
) -> RequirementRenderArtifact:
    """Return the stored artifact for this identity, rendering only when absent.

    ``producer`` is not called when a ready artifact already exists, so a frozen
    delivery is never silently re-rendered with newer code or templates.
    """

    identity = render_identity(request)
    existing = find_artifact(db, request.project_id, identity)
    if existing is not None:
        if existing.status == "ready":
            return existing
        raise RenderArtifactError(
            "artifact_failed",
            f"该渲染身份上次渲染失败（{existing.error_code or 'unknown'}），请修复后重新导出。",
        )

    payload = producer()
    if not payload:
        raise RenderArtifactError("empty_output", "渲染结果为空，无法作为正式文件保存。")
    file_sha256 = hashlib.sha256(payload).hexdigest()
    stored = get_storage_service().save(
        payload, file_name=request.file_name, project_id=request.project_id
    )
    row = RequirementRenderArtifact(
        project_id=request.project_id,
        requirement_id=request.requirement_id,
        source_kind=request.source_kind,
        source_id=request.source_id,
        format=request.format,
        file_name=request.file_name,
        media_type=request.media_type or MEDIA_TYPES.get(request.format, "application/octet-stream"),
        content_hash=request.content_hash,
        snapshot_hash=request.snapshot_hash,
        template_sha256=request.template_sha256,
        renderer_version=request.renderer_version,
        config_version=request.config_version,
        render_identity=identity,
        file_sha256=file_sha256,
        file_size=len(payload),
        storage_key=stored.storage_key,
        storage_backend="local",
        status="ready",
        diagnostics_json=dict(request.diagnostics or {}),
        warnings_json=list(request.warnings or []),
        created_by=created_by,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent request won the race: fall back to its row, drop ours.
        db.rollback()
        winner = find_artifact(db, request.project_id, identity)
        if winner is None:
            raise RenderArtifactError("artifact_conflict", "渲染产物登记冲突，请重试。") from None
        return winner
    return row


def read_artifact_bytes(artifact: RequirementRenderArtifact) -> bytes:
    """Read the stored bytes and prove they are still the approved file."""

    if artifact.status != "ready" or not artifact.storage_key:
        raise RenderArtifactError("artifact_missing", "该渲染产物没有可读取的文件。")
    try:
        payload = get_storage_service().read(artifact.storage_key)
    except FileNotFoundError as exc:
        raise RenderArtifactError(
            "artifact_missing", "渲染产物文件已丢失，不能重新渲染替代历史正式文件，请联系管理员恢复存储。"
        ) from exc
    digest = hashlib.sha256(payload).hexdigest()
    if digest != artifact.file_sha256:
        raise RenderArtifactError(
            "artifact_integrity_failed",
            f"渲染产物完整性校验失败：登记 {artifact.file_sha256[:12]}…，实际 {digest[:12]}…。文件可能被替换或损坏。",
        )
    return payload


def list_artifacts(
    db: Session,
    project_id: int,
    requirement_id: int,
    *,
    source_kind: str | None = None,
    source_id: int | None = None,
) -> list[RequirementRenderArtifact]:
    statement = select(RequirementRenderArtifact).where(
        RequirementRenderArtifact.project_id == project_id,
        RequirementRenderArtifact.requirement_id == requirement_id,
    )
    if source_kind is not None:
        statement = statement.where(RequirementRenderArtifact.source_kind == source_kind)
    if source_id is not None:
        statement = statement.where(RequirementRenderArtifact.source_id == source_id)
    statement = statement.order_by(RequirementRenderArtifact.id)
    return list(db.scalars(statement))


def get_artifact(db: Session, project_id: int, requirement_id: int, artifact_id: int) -> RequirementRenderArtifact:
    row = db.scalar(
        select(RequirementRenderArtifact).where(
            RequirementRenderArtifact.id == artifact_id,
            RequirementRenderArtifact.project_id == project_id,
            RequirementRenderArtifact.requirement_id == requirement_id,
        )
    )
    if row is None:
        raise RenderArtifactError("artifact_not_found", "找不到该渲染产物。")
    return row
