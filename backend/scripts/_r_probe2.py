"""Read-only probe: index tables, milvus collections, knowledge documents."""
from sqlalchemy import text

from app.core.database import SessionLocal


def main() -> None:
    db = SessionLocal()

    def q(sql: str):
        try:
            return db.execute(text(sql)).all()
        except Exception as error:  # noqa: BLE001
            db.rollback()
            return [("ERR", str(error)[:160])]

    print("index_tables", q(
        "select table_name from information_schema.tables "
        "where table_schema='public' and (table_name like '%semantic%' or table_name like '%index%') "
        "order by 1"))
    print("eval_tables", q(
        "select table_name from information_schema.tables "
        "where table_schema='public' and table_name like '%evaluation%' order by 1"))
    print("documents", q(
        "select id, project_id, title, source_category, lifecycle_status from knowledge_documents order by id"))
    print("versions", q(
        "select id, document_id, project_id, publisher, regulatory_version, effective_at, lifecycle_status "
        "from knowledge_document_versions order by id"))
    print("units", q(
        "select id, project_id, document_id, knowledge_type, title, target_field_code, "
        "length(content) from knowledge_units order by id"))
    print("eval_case_cols", q(
        "select column_name from information_schema.columns where table_name='rag_evaluation_cases' order by ordinal_position"))
    print("eval_run_cols", q(
        "select column_name from information_schema.columns where table_name='rag_evaluation_runs' order by ordinal_position"))
    db.close()


if __name__ == "__main__":
    main()
