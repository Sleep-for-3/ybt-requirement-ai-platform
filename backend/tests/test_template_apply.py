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
