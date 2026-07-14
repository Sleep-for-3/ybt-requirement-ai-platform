"""knowledge rag evaluation

Revision ID: 202607140006
Revises: 202607140005
"""
import sqlalchemy as sa
from alembic import op
from app.models import (AIUserFeedback,EmbeddingRecord,KnowledgeDocumentVersion,KnowledgeEntityLink,KnowledgeIngestionTask,KnowledgeUnit,ModelCallLog,ModelProfile,PromptTemplateVersion,RagEvaluationCase,RagEvaluationResult,RagEvaluationRun,RetrievalLog)

revision="202607140006";down_revision="202607140005";branch_labels=None;depends_on=None

def _add(table,name,column):
    if name not in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:op.add_column(table,column)

def _add_with_batch(table,name,column):
    if name not in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)

def _drop_indexes_for_columns(table, columns):
    target=set(columns)
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if target.intersection(index.get("column_names") or []):
            op.drop_index(index["name"],table_name=table)

def upgrade():
    bind=op.get_bind()
    for table in [KnowledgeDocumentVersion.__table__,KnowledgeUnit.__table__,KnowledgeEntityLink.__table__,KnowledgeIngestionTask.__table__,EmbeddingRecord.__table__,RetrievalLog.__table__,ModelProfile.__table__,PromptTemplateVersion.__table__,RagEvaluationCase.__table__,RagEvaluationRun.__table__,RagEvaluationResult.__table__,AIUserFeedback.__table__,ModelCallLog.__table__]:table.create(bind=bind,checkfirst=True)
    for name,column in {
        "knowledge_type":sa.Column("knowledge_type",sa.String(50),server_default="manual_note"),"knowledge_scope":sa.Column("knowledge_scope",sa.String(50),server_default="project"),"institution_name":sa.Column("institution_name",sa.String(255)),"document_status":sa.Column("document_status",sa.String(50),server_default="pending"),"confidentiality_level":sa.Column("confidentiality_level",sa.String(50),server_default="internal"),"file_hash":sa.Column("file_hash",sa.String(64)),"current_version_no":sa.Column("current_version_no",sa.Integer,server_default="1"),"parse_status":sa.Column("parse_status",sa.String(50),server_default="pending"),"parse_summary_json":sa.Column("parse_summary_json",sa.JSON,server_default="{}"),"warnings_json":sa.Column("warnings_json",sa.JSON,server_default="[]"),"error_message":sa.Column("error_message",sa.Text),"created_by":sa.Column("created_by",sa.String(100)),"updated_at":sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now())}.items():_add("knowledge_documents",name,column)
    for table in ["catalog_tables","catalog_columns","source_tables","mart_tables"]:_add(table,"database_name",sa.Column("database_name",sa.String(255)))
    _add_with_batch("candidate_source_recommendations","retrieval_log_id",sa.Column("retrieval_log_id",sa.Integer,sa.ForeignKey("retrieval_logs.id",name="fk_candidate_recommendation_retrieval_log")))
    _add("candidate_source_recommendations","knowledge_unit_ids_json",sa.Column("knowledge_unit_ids_json",sa.JSON,server_default="[]"));_add("candidate_source_recommendations","citation_summary_json",sa.Column("citation_summary_json",sa.JSON,server_default="[]"));_add("candidate_source_recommendations","recommendation_basis",sa.Column("recommendation_basis",sa.String(100)))
    prompt_table=sa.table("prompt_template_versions",sa.column("prompt_key",sa.String),sa.column("version_no",sa.Integer),sa.column("system_prompt",sa.Text),sa.column("user_prompt_template",sa.Text),sa.column("output_schema_json",sa.JSON),sa.column("enabled",sa.Boolean))
    prompt_labels = {
        "scenario_business_mapping": "场景业务口径",
        "scenario_technical_lineage": "场景技术溯源",
        "source_to_mart_mapping": "业务系统到监管集市",
        "mart_to_ybt_mapping": "监管集市到一表通",
        "source_recommendation_explanation": "来源字段推荐解释",
        "regulatory_field_explanation": "监管字段解释",
    }
    op.bulk_insert(
        prompt_table,
        [
            {
                "prompt_key": key,
                "version_no": 1,
                "system_prompt": f"你正在生成{label}。仅依据所给证据生成可验证草稿，不得虚构来源；证据不足必须标记待确认。",
                "user_prompt_template": "目标：{target}\n证据：{evidence}",
                "output_schema_json": {},
                "enabled": True,
            }
            for key, label in prompt_labels.items()
        ],
    )

def downgrade():
    candidate_columns = [
        "recommendation_basis",
        "citation_summary_json",
        "knowledge_unit_ids_json",
        "retrieval_log_id",
    ]
    _drop_indexes_for_columns("candidate_source_recommendations",candidate_columns)
    with op.batch_alter_table("candidate_source_recommendations") as batch:
        for column in candidate_columns:
            batch.drop_column(column)
    for table in ["catalog_tables", "catalog_columns", "source_tables", "mart_tables"]:
        _drop_indexes_for_columns(table,["database_name"])
        with op.batch_alter_table(table) as batch:
            batch.drop_column("database_name")
    knowledge_document_columns = [
        "updated_at",
        "created_by",
        "error_message",
        "warnings_json",
        "parse_summary_json",
        "parse_status",
        "current_version_no",
        "file_hash",
        "confidentiality_level",
        "document_status",
        "institution_name",
        "knowledge_scope",
        "knowledge_type",
    ]
    _drop_indexes_for_columns("knowledge_documents",knowledge_document_columns)
    with op.batch_alter_table("knowledge_documents") as batch:
        for column in knowledge_document_columns:
            batch.drop_column(column)
    for name in ["ModelCallLog","AIUserFeedback","RagEvaluationResult","RagEvaluationRun","RagEvaluationCase","PromptTemplateVersion","ModelProfile","RetrievalLog","EmbeddingRecord","KnowledgeIngestionTask","KnowledgeEntityLink","KnowledgeUnit","KnowledgeDocumentVersion"]:
        model=globals()[name];model.__table__.drop(bind=op.get_bind(),checkfirst=True)
