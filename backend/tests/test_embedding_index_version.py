from app.models import EmbeddingIndexVersion, Project
from app.services.semantic_index.versioning import (
    activate_index_version,
    build_collection_name,
    build_model_fingerprint,
)


def test_model_fingerprint_and_collection_name_are_stable_and_secret_free():
    fingerprint = build_model_fingerprint(
        provider="local_vllm",
        base_url="http://embedding.internal:8000/v1?api_key=must-not-leak",
        model_name="bge-m3",
        dimension=1024,
    )
    collection = build_collection_name(project_id=42, version_id=7, model_fingerprint=fingerprint, dimension=1024)

    assert fingerprint == build_model_fingerprint(
        provider="local_vllm",
        base_url="http://embedding.internal:8000/v1?different=secret",
        model_name="bge-m3",
        dimension=1024,
    )
    assert "secret" not in fingerprint
    assert collection.startswith("ybt_semantic_p42_v7_")
    assert collection.endswith("_d1024")


def test_activation_supersedes_old_index_atomically(db_session):
    project = Project(name="索引版本测试")
    db_session.add(project)
    db_session.flush()
    first = EmbeddingIndexVersion(
        project_id=project.id,
        provider="local_vllm",
        model_name="bge-m3",
        model_fingerprint="a" * 64,
        vector_dimension=1024,
        distance_metric="COSINE",
        collection_name="semantic_first",
        corpus_hash="1" * 64,
        status="active",
    )
    second = EmbeddingIndexVersion(
        project_id=project.id,
        provider="local_vllm",
        model_name="bge-m3",
        model_fingerprint="b" * 64,
        vector_dimension=1024,
        distance_metric="COSINE",
        collection_name="semantic_second",
        corpus_hash="2" * 64,
        status="validated",
    )
    db_session.add_all([first, second])
    db_session.flush()

    activate_index_version(db_session, second)
    db_session.flush()

    assert first.status == "superseded"
    assert second.status == "active"
    assert second.activated_at is not None
