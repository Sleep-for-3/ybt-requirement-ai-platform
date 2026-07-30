import hashlib
from datetime import datetime, timezone

from app.services.vector.base import VectorRecord


def build_knowledge_vector_record(
    unit,
    embedding: list[float],
    *,
    index_version_id: int | None = None,
    model_fingerprint: str | None = None,
    institution_id: int | None = None,
) -> VectorRecord:
    """Build a metadata-only vector record; knowledge text remains in the business DB."""
    if index_version_id is None or model_fingerprint is None:
        record_id = f"knowledge-unit-{unit.id}"
    else:
        material = (
            f"{index_version_id}:{unit.document_version_id}:{unit.id}:"
            f"{unit.content_hash}:{model_fingerprint}"
        )
        record_id = hashlib.sha256(material.encode("utf-8")).hexdigest()
    metadata = {
        "knowledge_unit_id": unit.id,
        "project_id": unit.project_id,
        "knowledge_scope": unit.knowledge_scope,
        "institution_name": unit.institution_name,
        "knowledge_type": unit.knowledge_type,
        "target_field_code": unit.target_field_code,
        "scenario_id": unit.scenario_id,
        "confidentiality_level": unit.confidentiality_level,
        "document_version_id": unit.document_version_id,
        "content_hash": unit.content_hash,
    }
    if index_version_id is not None and model_fingerprint is not None:
        metadata.update({
            "institution_id": institution_id or 0,
            "chunk_id": unit.id,
            "document_id": unit.document_id,
            "classification": unit.confidentiality_level,
            "citation_id": f"knowledge-unit-{unit.id}",
            "embedding_model_fingerprint": model_fingerprint,
            "embedding_index_version_id": index_version_id,
            "created_at_epoch": int(datetime.now(timezone.utc).timestamp()),
        })
    return VectorRecord(
        id=record_id,
        embedding=embedding,
        content="",
        metadata=metadata,
    )
