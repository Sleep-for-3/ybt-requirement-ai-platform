import json
import sqlite3
import tempfile
from pathlib import Path

import httpx
from openpyxl import Workbook


def main() -> None:
    base = "http://127.0.0.1:8000/api"
    client = httpx.Client(timeout=90, trust_env=False)

    project = _post_json(
        client,
        f"{base}/projects",
        {
            "name": "增强验收测试项目",
            "bank_name": "示例银行",
            "description": "验证模板、数据源、自然语言任务和口径生成",
        },
    )
    project_id = project["id"]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        excel_path = temp_path / "一表通模板.xlsx"
        sqlite_path = temp_path / "ecif_query.db"
        _write_template(excel_path)
        _write_sqlite_source(sqlite_path)

        with excel_path.open("rb") as file:
            template = _post_file(
                client,
                f"{base}/templates/upload",
                data={"project_id": str(project_id)},
                files={"file": ("一表通模板.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        apply_result = _post_json(client, f"{base}/templates/{template['template_id']}/apply", {})

        fields = client.get(f"{base}/fields", params={"project_id": project_id})
        fields.raise_for_status()
        field = next(item for item in fields.json() if item["field_code"] == "CERT_TYPE")

        datasource = _post_json(
            client,
            f"{base}/projects/{project_id}/datasources",
            {
                "name": "ecif_query",
                "display_name": "ECIF SQLite 测试库",
                "db_type": "sqlite",
                "database_name": str(sqlite_path),
                "readonly_flag": True,
                "enabled": True,
            },
        )
        datasource_test = _post_json(client, f"{base}/datasources/{datasource['id']}/test", {})

        task_create = _post_json(
            client,
            f"{base}/nl-tasks",
            {
                "project_id": project_id,
                "text": "使用 ecif_query 查询 ecif_customer 表 cert_type 字段的空值率和枚举分布",
            },
        )
        task_run = _post_json(client, f"{base}/nl-tasks/{task_create['task_id']}/run", {})

        business_system = _post_json(
            client,
            f"{base}/projects/{project_id}/business-systems",
            {"system_code": "ECIF", "system_name": "客户信息系统", "owner_department": "数据管理部", "enabled": True},
        )
        source_table = _post_json(
            client,
            f"{base}/business-systems/{business_system['id']}/source-tables",
            {
                "table_code": "ecif_customer",
                "table_name": "客户基本信息表",
                "table_comment": "ECIF 客户主表",
                "datasource_id": datasource["id"],
                "physical_table_name": "ecif_customer",
            },
        )
        source_field = _post_json(
            client,
            f"{base}/source-tables/{source_table['id']}/source-fields",
            {
                "field_code": "cert_type",
                "field_name": "证件类型",
                "field_type": "text",
                "field_comment": "客户证件类型",
                "physical_column_name": "cert_type",
            },
        )
        mart_table = _post_json(
            client,
            f"{base}/projects/{project_id}/mart-tables",
            {
                "table_code": "mart_customer",
                "table_name": "监管客户集市表",
                "subject_area": "客户",
                "table_comment": "一表通客户主题中间层",
                "is_existing": False,
            },
        )
        mart_field = _post_json(
            client,
            f"{base}/mart-tables/{mart_table['id']}/mart-fields",
            {
                "field_code": "cert_type",
                "field_name": "客户证件类型",
                "field_type": "varchar(20)",
                "field_comment": "统一监管客户证件类型",
                "is_existing": False,
            },
        )
        source_to_mart = _post_json(
            client,
            f"{base}/mart-fields/{mart_field['id']}/source-to-mart-mappings",
            {
                "mapping_name": "ECIF 证件类型入监管集市",
                "source_system_summary": "ECIF",
                "source_tables_summary": "ecif_customer",
                "source_fields_summary": "cert_type",
                "business_rule": "从 ECIF 客户基本信息表取客户证件类型。",
            },
        )
        mart_to_ybt = _post_json(
            client,
            f"{base}/target-fields/{field['id']}/mart-to-ybt-mappings",
            {
                "mart_field_id": mart_field["id"],
                "mapping_name": "监管集市证件类型到一表通",
                "mart_table_summary": "mart_customer",
                "mart_field_summary": "cert_type",
                "business_rule": "从监管客户集市字段取值并转换为一表通代码。",
            },
        )
        source_evidence = _post_json(
            client,
            f"{base}/mappings/source_to_mart/{source_to_mart['id']}/evidence",
            {
                "evidence_type": "source_field",
                "evidence_id": source_field["id"],
                "source_name": "ECIF.ecif_customer.cert_type",
                "location_text": "源字段",
                "quoted_content": "客户证件类型字段",
                "evidence_summary": "证明监管集市 cert_type 来源于 ECIF cert_type。",
            },
        )
        ybt_evidence = _post_json(
            client,
            f"{base}/mappings/mart_to_ybt/{mart_to_ybt['id']}/evidence",
            {
                "evidence_type": "db_query_result",
                "evidence_id": task_run["id"],
                "source_name": "自然语言任务结果",
                "location_text": "cert_type 枚举分布",
                "quoted_content": json.dumps(task_run["result_summary_json"], ensure_ascii=False),
                "evidence_summary": "证明 cert_type 有 01、02 和空值，需要口径说明码值转换和空值处理。",
            },
        )
        source_draft = _post_json(client, f"{base}/source-to-mart-mappings/{source_to_mart['id']}/generate-draft", {})
        ybt_draft = _post_json(client, f"{base}/mart-to-ybt-mappings/{mart_to_ybt['id']}/generate-draft", {})
        source_final = _put_json(
            client,
            f"{base}/source-to-mart-mappings/{source_to_mart['id']}",
            {
                "final_content": "业务系统到监管集市：ECIF.ecif_customer.cert_type 进入 mart_customer.cert_type，按有效客户过滤，空值列为待确认。",
                "open_questions": "请确认 ECIF 证件类型码值是否已经与最新监管代码集一致。",
            },
        )
        ybt_final = _put_json(
            client,
            f"{base}/mart-to-ybt-mappings/{mart_to_ybt['id']}",
            {
                "final_content": "监管集市到一表通：mart_customer.cert_type 映射到 CERT_TYPE，并按一表通代码集转换。",
                "open_questions": "请确认报送日期内有效客户判定规则。",
            },
        )
        source_approved = _post_json(client, f"{base}/source-to-mart-mappings/{source_final['id']}/approve", {"reviewed_by": "smoke"})
        ybt_approved = _post_json(client, f"{base}/mart-to-ybt-mappings/{ybt_final['id']}/approve", {"reviewed_by": "smoke"})
        field_export = client.get(f"{base}/target-fields/{field['id']}/export/mapping-document", params={"format": "markdown"})
        field_export.raise_for_status()
        markdown = field_export.json()["content"]
        required_sections = [
            "一表通字段信息",
            "监管集市字段设计",
            "业务系统到监管集市取数口径",
            "监管集市到一表通取数口径",
            "参考依据",
            "待确认问题",
            "审核状态",
        ]
        missing_sections = [section for section in required_sections if section not in markdown]
        if missing_sections:
            raise AssertionError(f"导出文档缺少章节: {missing_sections}")

        legacy_mapping = _post_json(
            client,
            f"{base}/fields/{field['id']}/generate-mapping",
            {
                "include_template": True,
                "include_documents": True,
                "include_sql_parse_results": True,
                "include_nl_task_results": True,
            },
        )
        draft = legacy_mapping["draft"]
        evidence_types = sorted({item["evidence_type"] for item in draft["evidences"]})

        output = {
            "project_id": project_id,
            "template_status": template["parse_status"],
            "template_field_count": template["field_count"],
            "apply_result": apply_result,
            "field_id": field["id"],
            "datasource_id": datasource["id"],
            "datasource_test": datasource_test,
            "task_status": task_run["status"],
            "extracted": {
                "datasource": task_run["datasource_name"],
                "table": task_run["extracted_table_name"],
                "field": task_run["extracted_field_name"],
            },
            "null_profile": task_run["result_summary_json"]["null_profile"],
            "distinct_profile": task_run["result_summary_json"]["distinct_profile"],
            "enum_distribution_rows": task_run["result_summary_json"]["enum_distribution"]["row_count"],
            "business_system_id": business_system["id"],
            "source_field_id": source_field["id"],
            "mart_field_id": mart_field["id"],
            "source_to_mart_mapping_status": source_approved["mapping_status"],
            "mart_to_ybt_mapping_status": ybt_approved["mapping_status"],
            "source_draft_confidence": source_draft["confidence_level"],
            "ybt_draft_confidence": ybt_draft["confidence_level"],
            "mapping_evidence_ids": [source_evidence["id"], ybt_evidence["id"]],
            "export_markdown_chars": len(markdown),
            "draft_id": draft["id"],
            "evidence_types": evidence_types,
            "template_reference_summary": draft.get("template_reference_summary"),
            "db_query_summary": draft.get("db_query_summary"),
            "evidence_completeness": draft.get("evidence_completeness"),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


def _write_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "客户信息表"
    sheet.append(["表编号", "表名称", "字段代码", "字段中文名", "字段类型", "是否必填", "字段定义", "监管说明"])
    sheet.append(["YBT_CUSTOMER", "客户信息表", "CERT_TYPE", "客户证件类型", "varchar(20)", "是", "客户身份证件类型", "按监管代码集转换"])
    sheet.append(["YBT_CUSTOMER", "客户信息表", "CUSTOMER_ID", "客户编号", "varchar(64)", "是", "客户唯一编号", "不能为空"])
    workbook.save(path)


def _write_sqlite_source(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("create table ecif_customer (cert_type text, customer_name text)")
        connection.executemany(
            "insert into ecif_customer (cert_type, customer_name) values (?, ?)",
            [("01", "张三"), ("01", "李四"), ("02", "王五"), (None, "赵六")],
        )
        connection.commit()
    finally:
        connection.close()


def _post_json(client: httpx.Client, url: str, payload: dict) -> dict:
    response = client.post(url, json=payload)
    response.raise_for_status()
    return response.json()


def _post_file(client: httpx.Client, url: str, data: dict, files: dict) -> dict:
    response = client.post(url, data=data, files=files)
    response.raise_for_status()
    return response.json()


def _put_json(client: httpx.Client, url: str, payload: dict) -> dict:
    response = client.put(url, json=payload)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    main()
