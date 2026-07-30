import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select, update

from app.core.settings import get_settings
from app.models import EmbeddingIndexVersion


def build_model_fingerprint(
    *,
    provider: str,
    base_url: str,
    model_name: str,
    dimension: int,
    normalization_config: str = "provider-default-v1",
    index_config_version: str = "formal-semantic-index-v1",
) -> str:
    """Build a stable runtime identity without credentials or URL query values."""
    parsed = urlsplit(base_url)
    safe_endpoint = f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}"
    if parsed.port:
        safe_endpoint += f":{parsed.port}"
    safe_endpoint += parsed.path.rstrip("/")
    material = json.dumps(
        {
            "provider": provider.strip().lower(),
            "endpoint": safe_endpoint,
            "model": model_name.strip(),
            "dimension": int(dimension),
            "normalization_config": normalization_config,
            "index_config_version": index_config_version,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_collection_name(
    *,
    project_id: int,
    version_id: int,
    model_fingerprint: str,
    dimension: int,
    prefix: str | None = None,
) -> str:
    collection_prefix = prefix or get_settings().milvus_collection_prefix
    raw = f"{collection_prefix}_p{project_id}_v{version_id}_{model_fingerprint[:12]}_d{dimension}"
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw)[:255]


def get_active_index_version(db, project_id: int) -> EmbeddingIndexVersion | None:
    return db.scalar(
        select(EmbeddingIndexVersion)
        .where(
            EmbeddingIndexVersion.project_id == project_id,
            EmbeddingIndexVersion.status == "active",
        )
        .order_by(EmbeddingIndexVersion.activated_at.desc(), EmbeddingIndexVersion.id.desc())
    )


def activate_index_version(db, version: EmbeddingIndexVersion) -> None:
    """Switch readers only after a version has been fully validated."""
    db.execute(
        update(EmbeddingIndexVersion)
        .where(
            EmbeddingIndexVersion.project_id == version.project_id,
            EmbeddingIndexVersion.status == "active",
            EmbeddingIndexVersion.id != version.id,
        )
        .values(status="superseded")
    )
    now = datetime.now(timezone.utc)
    version.status = "active"
    version.activated_at = now
    version.completed_at = now
