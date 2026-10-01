"""Synthetic acceptance data for the "regulatory field analysis" agent run.

Fictional demo data only — no real bank data. It gives the governed chain
something real to work with:

* a normative regulatory clause (``source_category="regulatory_formal"``) with a
  clause-shaped heading and a keyword index entry,
* a secondary-market forfeiting target field plus a scenario mapping,
* a source catalog column, a registered source field,
* a SQL script whose statement filters ``status = 'ACTIVE'``,
* a lineage path target ← mart ← source.

Shared by the pytest acceptance test and the live demo seeding script.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BusinessSystem,
    CatalogColumn,
    CatalogSchema,
    CatalogTable,
    DataSource,
    Institution,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    LineageEdge,
    LineageNode,
    ProductScenario,
    Project,
    ProjectMembership,
    ScenarioBusinessMapping,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    StoredFile,
    SourceTable,
    SqlStatement,
    TargetField,
    TargetTable,
    User,
)
from app.services.llm.execution_metadata import stable_hash
from app.services.retrieval.keyword_index import index_knowledge_unit

INSTITUTION_CODE = "ACCEPT_AGENT_BANK"
USERNAME = "agent_acceptance"
PROJECT_NAME = "二级市场福费廷报送验收项目"
OBJECTIVE = "分析二级市场福费廷报送需求"
FIELD_CODE = "FT_BAL"
FIELD_NAME = "福费廷余额"
CLAUSE_HEADING = "第五条 二级市场福费廷余额报送口径"
CLAUSE_TEXT = (
    "第五条 二级市场福费廷余额报送口径：二级市场福费廷余额（字段 FT_BAL / 福费廷余额）"
    "应按交易持有状态统计，仅纳入持有到期或已确认的福费廷交易，"
    "不得包含已终止或未确认状态的交易金额。"
)
SQL_TEXT = (
    "select sum(deal_amount) as ft_bal\n"
    "from ft_trade_detail\n"
    "where deal_status in ('ACTIVE', 'MATURED')\n"
    "  and market_type = 'SECONDARY'\n"
)


def _get_or_create(db: Session, model, *, defaults: dict, **lookup):
    row = db.scalar(select(model).filter_by(**lookup))
    if row is None:
        row = model(**lookup, **defaults)
        db.add(row)
        db.flush()
    return row


def seed_agent_acceptance(db: Session) -> dict:
    institution = _get_or_create(
        db, Institution, institution_code=INSTITUTION_CODE,
        defaults={"institution_name": "验收测试银行", "institution_type": "bank", "status": "active"},
    )
    user = _get_or_create(
        db, User, username=USERNAME,
        defaults={"display_name": "Agent 验收用户", "status": "active"},
    )
    project = _get_or_create(
        db, Project, name=PROJECT_NAME,
        defaults={"institution_id": institution.id, "project_status": "active",
                  "confidentiality_level": "internal", "governance_workflow_enabled": True},
    )
    if db.scalar(select(ProjectMembership).where(
            ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id)) is None:
        db.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                 project_role="project_manager", status="active"))
        db.flush()

    target_table = _get_or_create(
        db, TargetTable, project_id=project.id, table_code="YBT_FT",
        defaults={"table_name": "福费廷报送表", "description": "二级市场福费廷报送目标表"},
    )
    target_field = _get_or_create(
        db, TargetField, project_id=project.id, target_table_id=target_table.id, field_code=FIELD_CODE,
        defaults={"field_name": FIELD_NAME,
                  "regulatory_description": "仅统计持有到期或已确认的二级市场福费廷交易余额"},
    )
    scenario = _get_or_create(
        db, ProductScenario, project_id=project.id, scenario_code="SECONDARY_MARKET_FORFAITING",
        defaults={"scenario_name": "二级市场福费廷", "scenario_type": "business", "enabled": True, "sort_order": 1},
    )
    mapping = _get_or_create(
        db, ScenarioBusinessMapping, project_id=project.id, target_field_id=target_field.id,
        scenario_id=scenario.id, defaults={"business_definition": "二级市场福费廷余额业务口径（合成验收数据）"},
    )

    business_system = _get_or_create(
        db, BusinessSystem, project_id=project.id, system_code="FT_SYS",
        defaults={"system_name": "福费廷业务系统"},
    )
    source_table = _get_or_create(
        db, SourceTable, project_id=project.id, table_code="FT_TRADE_DETAIL",
        defaults={"table_name": "福费廷交易明细", "business_system_id": business_system.id,
                  "physical_table_name": "ft_trade_detail"},
    )
    source_field = _get_or_create(
        db, SourceField, project_id=project.id, source_table_id=source_table.id, field_code="DEAL_AMOUNT",
        defaults={"field_name": "交易金额", "physical_column_name": "deal_amount"},
    )

    datasource = _get_or_create(
        db, DataSource, project_id=project.id, name="验收测试只读数据源",
        defaults={"db_type": "postgresql", "enabled": True},
    )
    schema = _get_or_create(
        db, CatalogSchema, project_id=project.id, datasource_id=datasource.id, schema_name="public",
        defaults={},
    )
    catalog_table = _get_or_create(
        db, CatalogTable, project_id=project.id, datasource_id=datasource.id,
        catalog_schema_id=schema.id, schema_name="public", table_name="ft_trade_detail",
        defaults={"table_comment": "福费廷交易明细表", "enabled": True},
    )
    catalog_column = _get_or_create(
        db, CatalogColumn, project_id=project.id, datasource_id=datasource.id,
        catalog_table_id=catalog_table.id, schema_name="public", table_name="ft_trade_detail",
        column_name="ft_balance",
        defaults={"column_comment": "二级市场福费廷余额（合成验收数据）", "data_type": "numeric",
                  "nullable": True, "is_primary_key": False, "enabled": True},
    )

    document = _get_or_create(
        db, KnowledgeDocument, project_id=project.id, file_name="二级市场福费廷报送管理办法.docx",
        defaults={"file_type": "docx", "source_type": "upload", "storage_path": "synthetic/acceptance/clause.docx",
                  "knowledge_type": "regulatory_clause", "knowledge_scope": "project",
                  "document_status": "active", "source_category": "regulatory_formal",
                  "publisher": "验收测试监管机构", "current_version_no": 1},
    )
    version = _get_or_create(
        db, KnowledgeDocumentVersion, project_id=project.id, document_id=document.id, version_no=1,
        defaults={"file_name": document.file_name, "storage_path": document.storage_path,
                  "file_hash": stable_hash({"doc": document.id, "v": 1}),
                  "lifecycle_status": "active", "parse_status": "parsed",
                  "publisher": "验收测试监管机构", "regulatory_version": "2026版"},
    )
    if document.current_version_id != version.id:
        document.current_version_id = version.id
        db.flush()
    unit = _get_or_create(
        db, KnowledgeUnit, project_id=project.id, document_id=document.id, document_version_id=version.id,
        title=CLAUSE_HEADING,
        defaults={"knowledge_type": "regulatory_clause", "knowledge_scope": "project", "unit_type": "clause",
                  "content": CLAUSE_TEXT, "normalized_content": CLAUSE_TEXT,
                  "source_file_name": document.file_name, "source_heading": CLAUSE_HEADING,
                  "target_field_code": FIELD_CODE, "target_field_name": FIELD_NAME,
                  "confidentiality_level": "internal", "enabled": True,
                  "content_hash": stable_hash({"clause": CLAUSE_TEXT})},
    )
    index_knowledge_unit(db, unit, replace=True)

    script = _get_or_create(
        db, ScriptFile, project_id=project.id, relative_path="sql/ft_balance.sql",
        defaults={"file_name": "ft_balance.sql", "file_type": "sql", "logical_target_name": FIELD_CODE,
                  "current_version_no": 1, "enabled": True},
    )
    script_storage = _get_or_create(
        db, StoredFile, project_id=project.id, storage_key="synthetic/acceptance/ft_balance.sql",
        defaults={"institution_id": institution.id, "original_file_name": "ft_balance.sql",
                  "content_type": "text/plain", "byte_size": len(SQL_TEXT.encode("utf-8")),
                  "content_hash": stable_hash({"sql": SQL_TEXT}), "classification": "internal",
                  "created_by": user.id, "enabled": True},
    )
    script_version = _get_or_create(
        db, ScriptFileVersion, project_id=project.id, script_file_id=script.id, version_no=1,
        defaults={"file_hash": stable_hash({"sql": SQL_TEXT}), "normalized_hash": stable_hash({"sql_norm": SQL_TEXT}),
                  "raw_content_storage_file_id": script_storage.id, "parse_status": "parsed",
                  "dialect": "postgresql", "change_note": "合成验收脚本"},
    )
    statement = _get_or_create(
        db, SqlStatement, project_id=project.id, script_file_version_id=script_version.id, statement_index=0,
        defaults={"statement_type": "select", "raw_sql_hash": stable_hash({"raw": SQL_TEXT}),
                  "normalized_sql": SQL_TEXT, "parse_status": "parsed", "dialect": "postgresql",
                  "source_line_start": 1, "source_line_end": 4},
    )

    source_node = _get_or_create(
        db, LineageNode, project_id=project.id, node_type="source_table", logical_name="ft_trade_detail",
        defaults={"table_name": "ft_trade_detail", "source_field_id": source_field.id,
                  "catalog_column_id": catalog_column.id},
    )
    mart_node = _get_or_create(
        db, LineageNode, project_id=project.id, node_type="mart_table", logical_name="mart_ft_balance",
        defaults={"table_name": "mart_ft_balance"},
    )
    target_node = _get_or_create(
        db, LineageNode, project_id=project.id, node_type="target_field", logical_name=f"{FIELD_CODE}",
        defaults={"column_name": "ft_bal", "target_field_id": target_field.id},
    )
    for source_id, target_id, edge_type in (
        (source_node.id, mart_node.id, "derives_from"),
        (mart_node.id, target_node.id, "derives_from"),
    ):
        existing = db.scalar(select(LineageEdge).where(
            LineageEdge.project_id == project.id, LineageEdge.source_node_id == source_id,
            LineageEdge.target_node_id == target_id))
        if existing is None:
            db.add(LineageEdge(project_id=project.id, script_file_version_id=script_version.id,
                               source_node_id=source_id, target_node_id=target_id, edge_type=edge_type,
                               transformation_type="aggregate", filter_condition="deal_status in ('ACTIVE','MATURED')"))
            db.flush()

    db.commit()
    return {
        "institution_id": institution.id, "user_id": user.id, "username": user.username,
        "project_id": project.id, "target_field_id": target_field.id, "target_table_id": target_table.id,
        "target_field_code": FIELD_CODE, "scenario_id": scenario.id, "mapping_id": mapping.id,
        "source_field_id": source_field.id, "source_table_id": source_table.id,
        "catalog_column_id": catalog_column.id, "unit_id": unit.id, "document_id": document.id,
        "document_version_id": version.id, "script_file_id": script.id,
        "script_file_version_id": script_version.id, "sql_statement_id": statement.id,
        "target_node_id": target_node.id, "objective": OBJECTIVE,
    }
