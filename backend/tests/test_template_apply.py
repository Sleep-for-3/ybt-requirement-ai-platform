from app.models import Project, TargetField, TargetTable, TemplateDocument, TemplateParseResult
from app.services.template_service import apply_template


def test_apply_template_creates_and_updates_target_tables_and_fields(db_session):
    project = Project(name="模板应用项目", bank_name="示例银行")
    db_session.add(project)
    db_session.flush()
    document = TemplateDocument(
        project_id=project.id,
        file_name="template.xlsx",
        file_type="xlsx",
        storage_path="/tmp/template.xlsx",
        sheet_names_json=["客户信息表"],
        parse_status="success",
    )
    db_session.add(document)
    db_session.flush()
    result = TemplateParseResult(
        template_document_id=document.id,
        project_id=project.id,
        sheet_name="客户信息表",
        table_code="YBT_CUSTOMER",
        table_name="客户信息表",
        field_count=2,
        raw_header_json=["字段代码", "字段名称"],
        parsed_rows_json=[
            {"field_code": "CERT_TYPE", "field_name": "客户证件类型", "field_type": "varchar(20)", "required_flag": True},
            {"field_code": "", "field_name": "缺少字段代码"},
        ],
        warnings_json=[],
    )
    db_session.add(result)
    db_session.commit()

    summary = apply_template(db_session, document.id)

    assert summary.created_tables == 1
    assert summary.created_fields == 1
    assert summary.skipped_rows == 1
    table = db_session.query(TargetTable).filter_by(project_id=project.id, table_code="YBT_CUSTOMER").one()
    field = db_session.query(TargetField).filter_by(target_table_id=table.id, field_code="CERT_TYPE").one()
    assert field.field_name == "客户证件类型"

    result.parsed_rows_json = [
        {"field_code": "CERT_TYPE", "field_name": "客户证件类型更新", "field_type": "varchar(20)", "required_flag": True}
    ]
    db_session.commit()
    second_summary = apply_template(db_session, document.id)

    assert second_summary.updated_tables == 1
    assert second_summary.updated_fields == 1
    updated_field = db_session.query(TargetField).filter_by(target_table_id=table.id, field_code="CERT_TYPE").one()
    assert updated_field.field_name == "客户证件类型更新"


def test_apply_template_writes_table_level_meta_without_overwriting(db_session):
    """表级口径只补空值：已人工维护的主题不能被模板再次覆盖。

    导出文档的“数据主题名称/采集范围/一表通报送范围确认”依赖这些列，
    但业务人员可能已在平台里改过，Apply 必须保留人工结论。
    """

    from app.models import TemplateVersion

    project = Project(name="表级口径项目", bank_name="示例银行")
    db_session.add(project)
    db_session.flush()
    document = TemplateDocument(
        project_id=project.id,
        file_name="survey.xlsx",
        file_type="xlsx",
        storage_path="/tmp/survey.xlsx",
        sheet_names_json=["T_8_1-贷款借据"],
        parse_status="success",
    )
    db_session.add(document)
    db_session.flush()
    version = TemplateVersion(
        template_document_id=document.id,
        project_id=project.id,
        version_no=1,
        template_code="survey-t8",
        status="active",
        file_name="survey.xlsx",
        file_type="xlsx",
        storage_path="/tmp/survey.xlsx",
        file_hash="a" * 64,
        sheet_names_json=["T_8_1-贷款借据"],
        parse_status="success",
        table_meta_json={
            "T_8_1": {
                "theme": "状态类数据",
                "filing_note": "全量借据",
                "reporting_domain_name": "默认报送数据域",
            }
        },
    )
    db_session.add(version)
    db_session.flush()
    document.current_version_id = version.id
    db_session.add(
        TemplateParseResult(
            template_document_id=document.id,
            template_version_id=version.id,
            project_id=project.id,
            sheet_name="T_8_1-贷款借据",
            table_code="T_8_1",
            table_name="贷款借据",
            field_count=1,
            raw_header_json=["数据项编码"],
            parsed_rows_json=[{"field_code": "H010001", "field_name": "借据ID"}],
            warnings_json=[],
        )
    )
    db_session.commit()

    apply_template(db_session, document.id)
    table = db_session.query(TargetTable).filter_by(project_id=project.id, table_code="T_8_1").one()
    assert table.theme == "状态类数据"
    assert table.filing_note == "全量借据"
    assert table.reporting_domain_name == "默认报送数据域"

    table.theme = "人工确认过的主题"
    db_session.commit()
    apply_template(db_session, document.id)
    db_session.refresh(table)
    assert table.theme == "人工确认过的主题"

def test_apply_template_skips_section_marker_rows_with_chinese_codes(db_session):
    """分段标记行不能变成字段。

    真实调研表的数据区中间夹着"辅助字段""数据项编码"这类分段标记行（表编号/表名称列为空）。
    早期解析把它们当字段导入，形成 field_code 为中文的假字段：没有脚本血缘、没有集市映射，
    却会让"字段总数/脚本覆盖 8/10"这类统计失真（真实事故：T_8_1 因此显示 8/10）。
    """

    project = Project(name="分段标记项目", bank_name="示例银行")
    db_session.add(project)
    db_session.flush()
    document = TemplateDocument(
        project_id=project.id,
        file_name="survey.xlsx",
        file_type="xlsx",
        storage_path="/tmp/survey.xlsx",
        sheet_names_json=["T_8_1-贷款借据"],
        parse_status="success",
    )
    db_session.add(document)
    db_session.flush()
    result = TemplateParseResult(
        template_document_id=document.id,
        project_id=project.id,
        sheet_name="T_8_1-贷款借据",
        table_code="T_8_1",
        table_name="贷款借据",
        field_count=2,
        raw_header_json=["数据项编码", "数据项名称"],
        parsed_rows_json=[
            {"field_code": "H010001", "field_name": "借据ID", "row_number": 5},
            {"field_code": "辅助字段", "field_name": "协管部门", "row_number": 13},
            {"field_code": "数据项编码", "field_name": "数据项名称", "row_number": 14},
        ],
        warnings_json=[],
    )
    db_session.add(result)
    db_session.commit()

    summary = apply_template(db_session, document.id)

    assert summary.created_fields == 1
    assert summary.skipped_rows == 2
    assert any("不是标识符" in warning for warning in summary.warnings)
    table = db_session.query(TargetTable).filter_by(project_id=project.id, table_code="T_8_1").one()
    codes = {row.field_code for row in db_session.query(TargetField).filter_by(target_table_id=table.id)}
    assert codes == {"H010001"}
