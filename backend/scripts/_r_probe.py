"""Read-only probe: knowledge base size, semantic index status, retrieval settings."""
from sqlalchemy import text

from app.core.settings import get_settings
from app.core.database import SessionLocal


def main() -> None:
    db = SessionLocal()

    def q(sql: str):
        try:
            return db.execute(text(sql)).all()
        except Exception as error:  # noqa: BLE001
            db.rollback()
            return [("ERR", str(error)[:160])]

    print("docs", q("select count(*) from knowledge_documents"))
    print("units", q("select count(*) from knowledge_units"))
    print("kw_rows", q("select count(*) from knowledge_keyword_indexes"))
    print("retrieval_logs", q("select count(*) from retrieval_logs"))
    print("index_versions", q(
        "select id, project_id, status, collection_name, vector_dimension, created_at "
        "from semantic_index_versions order by id desc limit 6"))
    print("units_by_type", q(
        "select knowledge_type, count(*) from knowledge_units group by 1 order by 2 desc limit 15"))
    print("units_by_project", q(
        "select project_id, count(*) from knowledge_units group by 1 order by 2 desc limit 10"))
    print("docs_by_category", q(
        "select source_category, count(*) from knowledge_documents group by 1 order by 2 desc limit 15"))
    print("eval_cases", q("select project_id, count(*) from rag_evaluation_cases group by 1"))
    print("eval_runs", q(
        "select id, project_id, status, total_cases, passed_cases, recall_at_k, created_at "
        "from rag_evaluation_runs order by id desc limit 5"))
    settings = get_settings()
    for name in (
        "fusion_strategy", "rrf_k", "hybrid_vector_weight", "hybrid_keyword_weight",
        "vector_top_k", "keyword_top_k", "hybrid_final_top_k", "reranker_enabled",
        "reranker_model", "reranker_top_k", "citation_support_check",
        "embedding_provider", "embedding_model", "embedding_dimension",
        "vector_store_provider", "llm_provider", "llm_model",
    ):
        print("setting", name, "=", getattr(settings, name, "<missing>"))
    db.close()


if __name__ == "__main__":
    main()
