"""P0-C 真实浏览器闭环的隔离夹具（写入真实 PostgreSQL 隔离库）。

合成场景：借据 → 合同 → 产品 → 产品期限方案 → 客户标识 → 来源库 → 数据集市 → 一表通。
仅用于本地隔离库 ybt_dsh_handoff_v2，不触碰任何生产库，也不写入真实客户资料。

可重复执行：同名对象复用，不删除任何既有数据。输出 JSON（含各 id 与账号），
供 scripts/vnext2_p0c_browser_e2e.mjs 使用。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    BusinessSystem,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    Project,
    SourceField,
    SourceToMartMapping,
    SourceTable,
    TargetField,
    TargetTable,
    User,
)
from app.models.governance import Institution, ProjectMembership  # noqa: E402
from app.models.requirement import Requirement  # noqa: E402
from app.services.auth.password import hash_password  # noqa: E402

INSTITUTION_CODE = "VNEXT2-P0C"
PROJECT_NAME = "VNEXT2 P0-C 浏览器闭环"
TABLE_CODE = "EAST_CUSTOMER"
REQUIREMENT_NAME = "根据借据关联产品生成一表通客户统一标识（VNEXT2 P0-C 浏览器闭环）"
PASSWORD = "Vnext2#P0C2026"

RULE_V1 = (
    "第十条 客户统一标识。一表通客户统一标识应取客户主数据中的客户编号，按客户粒度报送。\n"
    "第十一条 产品维度。通过借据关联产品信息时，若同一产品 ID 对应多个期限方案，"
    "产品维度必须使用“产品 ID + 期限编号”组合业务键，不得仅按产品 ID 关联，避免一对多放大。\n"
    "第十二条 空值处理。无法关联到唯一产品方案的记录不得随意填充默认产品，应形成待确认问题。\n"
    "（合成制度文本，仅用于验证，不代表任何真实银行监管口径。）"
)

USERS = [
    ("p0c-pm", "P0-C 项目经理", "project_manager"),
    ("p0c-biz", "P0-C 业务分析", "business_analyst"),
    ("p0c-tech", "P0-C 技术分析", "technical_analyst"),
    ("p0c-breview", "P0-C 业务审核", "business_reviewer"),
    ("p0c-treview", "P0-C 技术审核", "technical_reviewer"),
    ("p0c-freview", "P0-C 终审", "final_reviewer"),
]


def _user(db, username: str, display_name: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, display_name=display_name, password_hash=hash_password(PASSWORD),
                    status="active")
        db.add(user)
        db.flush()
    else:
        user.password_hash = hash_password(PASSWORD)
        user.status = "active"
    return user


def main() -> int:
    with SessionLocal() as db:
        institution = db.scalar(select(Institution).where(Institution.institution_code == INSTITUTION_CODE))
        if institution is None:
            institution = Institution(institution_code=INSTITUTION_CODE, institution_name="VNext2 合成验证机构")
            db.add(institution)
            db.flush()
        users = {}
        for username, display, role in USERS:
            user = _user(db, username, display)
            users[role] = user
        owner = users["project_manager"]

        project = db.scalar(select(Project).where(Project.name == PROJECT_NAME))
        if project is None:
            project = Project(name=PROJECT_NAME, institution_id=institution.id, project_owner_id=owner.id,
                              description="合成数据，仅用于 VNext2 P0-C 真实浏览器闭环")
            db.add(project)
            db.flush()
        else:
            project.institution_id = institution.id
            project.project_owner_id = owner.id
        for role, user in users.items():
            membership = db.scalar(select(ProjectMembership).where(
                ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id))
            if membership is None:
                db.add(ProjectMembership(project_id=project.id, user_id=user.id, project_role=role,
                                         status="active"))
            else:
                membership.project_role = role
                membership.status = "active"
        db.flush()

        table = db.scalar(select(TargetTable).where(
            TargetTable.project_id == project.id, TargetTable.table_code == TABLE_CODE))
        if table is None:
            table = TargetTable(project_id=project.id, table_code=TABLE_CODE, table_name="一表通客户信息表",
                                description="合成一表通客户表")
            db.add(table)
            db.flush()
        target = db.scalar(select(TargetField).where(
            TargetField.project_id == project.id, TargetField.target_table_id == table.id,
            TargetField.field_code == "CUSTOMER_ID"))
        if target is None:
            target = TargetField(project_id=project.id, target_table_id=table.id, field_code="CUSTOMER_ID",
                                 field_name="客户统一标识", field_type="varchar(64)", required_flag=True,
                                 regulatory_description="监管客户唯一标识")
            db.add(target)
            db.flush()

        system = db.scalar(select(BusinessSystem).where(
            BusinessSystem.project_id == project.id, BusinessSystem.system_code == "ECIF"))
        if system is None:
            system = BusinessSystem(project_id=project.id, system_code="ECIF", system_name="客户信息系统")
            db.add(system)
            db.flush()

        def source_table(code: str, name: str, comment: str) -> SourceTable:
            row = db.scalar(select(SourceTable).where(
                SourceTable.project_id == project.id, SourceTable.table_code == code))
            if row is None:
                row = SourceTable(project_id=project.id, business_system_id=system.id, table_code=code,
                                  table_name=name, table_comment=comment, schema_name="SRC",
                                  physical_table_name=code)
                db.add(row)
                db.flush()
            return row

        def source_field(table_row: SourceTable, code: str, name: str, comment: str) -> SourceField:
            row = db.scalar(select(SourceField).where(
                SourceField.project_id == project.id, SourceField.source_table_id == table_row.id,
                SourceField.field_code == code))
            if row is None:
                row = SourceField(project_id=project.id, source_table_id=table_row.id, field_code=code,
                                  field_name=name, field_comment=comment, physical_column_name=code)
                db.add(row)
                db.flush()
            return row

        loan = source_table("LOAN_IOU", "借据表", "核心借据")
        contract = source_table("CONTRACT", "合同表", "贷款合同")
        product = source_table("PRODUCT", "产品表", "产品主数据（产品ID存在重复）")
        term = source_table("PRODUCT_TERM", "产品期限方案表", "产品期限方案")
        for table_row, code, name, comment in [
            (loan, "LOAN_ID", "借据号", "借据主键"),
            (loan, "CUST_NO", "客户号", "借据上的客户号"),
            (loan, "PRODUCT_ID", "产品ID", "借据产品"),
            (loan, "TERM_NO", "期限编号", "借据期限方案"),
            (contract, "CONTRACT_ID", "合同号", "合同主键"),
            (product, "PRODUCT_ID", "产品ID", "产品主数据ID（允许重复）"),
            (product, "PRODUCT_NAME", "产品名称", "产品名称"),
            (term, "PRODUCT_ID", "产品ID", "期限方案所属产品"),
            (term, "TERM_NO", "期限编号", "期限方案编号"),
            (term, "TERM_DAYS", "期限天数", "期限天数"),
        ]:
            source_field(table_row, code, name, comment)

        mart_table = db.scalar(select(MartTable).where(
            MartTable.project_id == project.id, MartTable.table_code == "REG_CUSTOMER"))
        if mart_table is None:
            mart_table = MartTable(project_id=project.id, table_code="REG_CUSTOMER", table_name="监管客户集市表",
                                   table_comment="监管报送客户主题", schema_name="MART",
                                   physical_table_name="REG_CUSTOMER")
            db.add(mart_table)
            db.flush()
        mart_field = db.scalar(select(MartField).where(
            MartField.project_id == project.id, MartField.mart_table_id == mart_table.id,
            MartField.field_code == "CUSTOMER_ID"))
        if mart_field is None:
            mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="CUSTOMER_ID",
                                   field_name="客户统一标识", field_comment="监管集市客户统一标识",
                                   physical_column_name="CUSTOMER_ID")
            db.add(mart_field)
            db.flush()

        scenario = db.scalar(select(ProductScenario).where(
            ProductScenario.project_id == project.id, ProductScenario.scenario_code == "SYNTH"))
        if scenario is None:
            scenario = ProductScenario(project_id=project.id, scenario_code="SYNTH",
                                       scenario_name="个人消费贷产品方案")
            db.add(scenario)
            db.flush()

        cust_field = db.scalar(select(SourceField).where(
            SourceField.project_id == project.id, SourceField.source_table_id == loan.id,
            SourceField.field_code == "CUST_NO"))
        source_mapping = db.scalar(select(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project.id,
            SourceToMartMapping.mart_field_id == mart_field.id))
        if source_mapping is None:
            source_mapping = SourceToMartMapping(
                project_id=project.id, mart_field_id=mart_field.id,
                mapping_name="借据客户号入监管集市客户标识", mapping_status="approved",
                source_system_summary="客户信息系统", source_tables_summary="LOAN_IOU",
                source_fields_summary="CUST_NO", business_rule="按借据客户号映射客户统一标识",
                join_condition="SRC.LOAN_IOU.CUST_NO = ODS.CUSTOMER.CUST_NO",
                filter_condition="SRC.LOAN_IOU.IS_DELETED = 0",
                code_mapping_rule="TRIM(CUST_NO)", quality_check_rule="CUSTOMER_ID IS NOT NULL",
                confidence_level="high")
            db.add(source_mapping)
            db.flush()
        target_mapping = db.scalar(select(MartToYbtMapping).where(
            MartToYbtMapping.project_id == project.id, MartToYbtMapping.target_field_id == target.id))
        if target_mapping is None:
            target_mapping = MartToYbtMapping(
                project_id=project.id, target_field_id=target.id, mart_field_id=mart_field.id,
                mapping_name="监管集市到一表通客户标识", mapping_status="approved",
                business_rule="从监管客户集市输出客户统一标识",
                filter_condition="STAT_DATE = :report_date", validation_rule="长度不超过64位",
                confidence_level="high")
            db.add(target_mapping)
            db.flush()
        evidence = db.scalar(select(MappingEvidenceReference).where(
            MappingEvidenceReference.project_id == project.id,
            MappingEvidenceReference.mapping_type == "source_to_mart",
            MappingEvidenceReference.mapping_id == source_mapping.id))
        if evidence is None:
            db.add(MappingEvidenceReference(
                project_id=project.id, mapping_type="source_to_mart", mapping_id=source_mapping.id,
                evidence_type="source_field", evidence_id=cust_field.id if cust_field else None,
                source_name="ECIF.SRC.LOAN_IOU.CUST_NO", location_text="数据字典/借据表/CUST_NO",
                evidence_summary="已确认来源字段"))

        document = db.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.project_id == project.id,
            KnowledgeDocument.file_name == "一表通客户统一标识口径说明-2026v1.txt"))
        if document is None:
            document = KnowledgeDocument(
                project_id=project.id, file_name="一表通客户统一标识口径说明-2026v1.txt", file_type="txt",
                source_type="upload", storage_path="vnext2-p0c/knowledge/customer-id-2026v1.txt",
                knowledge_type="regulatory_formal", knowledge_scope="project", document_status="indexed",
                confidentiality_level="internal", current_version_no=1, source_category="regulatory_formal",
                regulatory_document_no="合成制度-2026-10", publisher="合成监管银行", created_by=owner.username)
            db.add(document)
            db.flush()
        version = db.scalar(select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.project_id == project.id,
            KnowledgeDocumentVersion.document_id == document.id, KnowledgeDocumentVersion.version_no == 1))
        if version is None:
            version = KnowledgeDocumentVersion(
                project_id=project.id, document_id=document.id, version_no=1,
                file_name=document.file_name, storage_path=document.storage_path,
                file_hash=hashlib.sha256(RULE_V1.encode("utf-8")).hexdigest(), parse_status="parsed",
                lifecycle_status="active", regulatory_version="2026-v1",
                effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                activated_at=datetime(2026, 1, 2, tzinfo=timezone.utc), reviewed_by="p0c-pm",
                created_by=owner.username)
            db.add(version)
            db.flush()
        document.current_version_id = version.id
        unit = db.scalar(select(KnowledgeUnit).where(
            KnowledgeUnit.project_id == project.id, KnowledgeUnit.document_id == document.id,
            KnowledgeUnit.title == "一表通客户统一标识填报口径"))
        if unit is None:
            unit = KnowledgeUnit(
                project_id=project.id, document_id=document.id, document_version_id=version.id,
                knowledge_type="regulatory_formal", knowledge_scope="project", unit_type="clause",
                title="一表通客户统一标识填报口径", content=RULE_V1,
                normalized_content=RULE_V1.replace(" ", ""), source_file_name=document.file_name,
                confidentiality_level="internal", enabled=True,
                content_hash=hashlib.sha256(RULE_V1.encode("utf-8")).hexdigest(),
                target_table_code="EAST_CUSTOMER", target_field_code="CUSTOMER_ID",
                metadata_json={"clause": "第十条"}, tags_json=["一表通", "客户标识"])
            db.add(unit)
            db.flush()

        requirement = db.scalar(select(Requirement).where(
            Requirement.project_id == project.id, Requirement.name == REQUIREMENT_NAME))
        scope = {
            "target_table_id": int(table.id),
            "field_ids": [int(target.id)],
            "scenario_id": int(scenario.id),
            "background": "根据借据信息中的产品编号与期限关联产品信息，形成一表通客户统一标识口径。",
            "document_ids": [int(document.id)],
            "source_table_ids": [int(loan.id), int(contract.id), int(product.id), int(term.id)],
            "mart_table_ids": [int(mart_table.id)],
        }
        if requirement is None:
            requirement = Requirement(project_id=project.id, name=REQUIREMENT_NAME, version=1,
                                      scope_json=scope, content_version=0)
            db.add(requirement)
            db.flush()
        else:
            requirement.scope_json = {**(requirement.scope_json or {}), **scope}
        db.commit()

        print(json.dumps({
            "project_id": int(project.id),
            "institution_id": int(institution.id),
            "requirement_id": int(requirement.id),
            "target_table_id": int(table.id),
            "target_field_id": int(target.id),
            "scenario_id": int(scenario.id),
            "document_id": int(document.id),
            "knowledge_version_id": int(version.id),
            "knowledge_unit_id": int(unit.id),
            "source_table_ids": [int(loan.id), int(contract.id), int(product.id), int(term.id)],
            "mart_table_id": int(mart_table.id),
            "password": PASSWORD,
            "users": {role: {"id": int(user.id), "username": user.username} for role, user in users.items()},
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
