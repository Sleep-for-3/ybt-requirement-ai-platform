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

        mapping = _post_json(
            client,
            f"{base}/fields/{field['id']}/generate-mapping",
            {
                "include_template": True,
                "include_documents": True,
                "include_sql_parse_results": True,
                "include_nl_task_results": True,
            },
        )
        draft = mapping["draft"]
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


if __name__ == "__main__":
    main()
