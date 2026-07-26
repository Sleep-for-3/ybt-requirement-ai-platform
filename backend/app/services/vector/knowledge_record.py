from app.services.vector.base import VectorRecord


def build_knowledge_vector_record(unit, embedding: list[float]) -> VectorRecord:
    """Build a metadata-only vector record; knowledge text remains in the business DB."""
    return VectorRecord(
        id=f"knowledge-unit-{unit.id}",
        embedding=embedding,
        content="",
        metadata={
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
        },
    )
