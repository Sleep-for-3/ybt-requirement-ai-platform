"""Read-only probe: embedding index versions, milvus collections, fastembed availability."""
from sqlalchemy import text

from app.core.database import SessionLocal


def main() -> None:
    db = SessionLocal()

    def q(sql: str):
        try:
            return db.execute(text(sql)).all()
        except Exception as error:  # noqa: BLE001
            db.rollback()
            return [("ERR", str(error)[:200])]

    print("index_versions", q(
        "select id, project_id, status, collection_name, vector_dimension, created_at "
        "from embedding_index_versions order by id desc limit 8"))
    print("index_cols", q(
        "select column_name from information_schema.columns "
        "where table_name='embedding_index_versions' order by ordinal_position"))
    from app.core.settings import get_settings
    settings = get_settings()
    try:
        from app.services.vector import get_vector_store
        print("vector provider", settings.vector_store_provider, settings.milvus_uri if hasattr(settings, "milvus_uri") else "<no milvus_uri>")
        from pymilvus import MilvusClient
        uri = getattr(settings, "milvus_uri", "") or "http://127.0.0.1:19530"
        client = MilvusClient(uri=uri)
        print("collections", client.list_collections())
        for name in client.list_collections():
            try:
                stats = client.get_collection_stats(name)
                print("  stats", name, stats)
            except Exception as error:  # noqa: BLE001
                print("  stats_err", name, str(error)[:120])
    except Exception as error:  # noqa: BLE001
        print("milvus_err", str(error)[:200])
    try:
        import fastembed
        print("fastembed", fastembed.__version__ if hasattr(fastembed, "__version__") else "installed")
    except Exception as error:  # noqa: BLE001
        print("fastembed_err", str(error)[:120])
    db.close()


if __name__ == "__main__":
    main()
