import json
import sqlite3
import tempfile
from io import BytesIO
from pathlib import Path

import httpx
from openpyxl import Workbook, load_workbook


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
        traceability_path = temp_path / "脱敏业务口径及溯源表.xlsx"
        sqlite_path = temp_path / "ecif_query.db"
        _write_template(excel_path)
        _write_traceability_template(traceability_path)
        _write_sqlite_source(sqlite_path)

        with excel_path.open("rb") as file:
            template = _post_file(
                client,
                f"{base}/templates/upload",
                data={"project_id": str(project_id)},
                files={"file": ("一表通模板.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        apply_result = _post_json(client, f"{base}/templates/{template['template_id']}/apply", {})

        with traceability_path.open("rb") as file:
            traceability_template = _post_file(
                client,
                f"{base}/traceability-templates/upload",
                data={"project_id": str(project_id)},
                files={"file": ("脱敏业务口径及溯源表.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        traceability_preview = _get_json(client, f"{base}/traceability-templates/{traceability_template['template_id']}/preview")
        traceability_apply = _post_json(client, f"{base}/traceability-templates/{traceability_template['template_id']}/apply", {})

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
        metadata_sync = _post_json(client, f"{base}/datasources/{datasource['id']}/metadata-sync", {"sync_mode": "full", "schema_names": [], "include_views": True})
        catalog_tables = _get_json(client, f"{base}/projects/{project_id}/catalog/tables?datasource_id={datasource['id']}")
        catalog_search = _post_json(client, f"{base}/projects/{project_id}/catalog/search", {"datasource_ids": [datasource["id"]], "query": "cert_type", "top_k": 20})
        catalog_cert_type = next(item for item in catalog_search["items"] if item["column_name"] == "cert_type")
        catalog_source_import = _post_json(client, f"{base}/catalog/columns/{catalog_cert_type['catalog_column_id']}/import-as-source-field", {"system_code": "CATALOG_ECIF", "system_name": "目录导入客户系统"})

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
        scenarios = _get_json(client, f"{base}/projects/{project_id}/scenarios")
        debit_scenario = next(item for item in scenarios if item["scenario_code"] == "DEBIT_CARD")
        business_mappings = _get_json(client, f"{base}/target-fields/{field['id']}/scenario-business-mappings")
        scenario_business = next(item for item in business_mappings if item["scenario_id"] == debit_scenario["id"])
        existing_lineages = _get_json(client, f"{base}/target-fields/{field['id']}/scenario-technical-lineages")
        existing_scenario_lineage = next(item for item in existing_lineages if item["scenario_id"] == debit_scenario["id"])
        source_recommendations = _post_json(
            client,
            f"{base}/target-fields/{field['id']}/scenarios/{debit_scenario['id']}/recommend-sources",
            {},
        )
        catalog_recommendation = next(item for item in source_recommendations["recommendations"] if item.get("catalog_column_id") == catalog_cert_type["catalog_column_id"])
        selected_recommendation = _post_json(
            client,
            f"{base}/source-recommendations/{catalog_recommendation['id']}/select",
            {},
        )
        scenario_lineage = selected_recommendation["lineage"]
        if scenario_lineage.get("source_field_english_name") != existing_scenario_lineage.get("source_field_english_name"):
            raise AssertionError("目录候选仅选择时不应自动写入技术来源")
        column_profile = _post_json(client, f"{base}/catalog/columns/{catalog_cert_type['catalog_column_id']}/profile", {
            "target_field_id": field["id"], "scenario_id": debit_scenario["id"], "source_recommendation_id": catalog_recommendation["id"],
            "metrics": ["null_rate", "distinct_count", "top_values", "min_max", "length_distribution"],
        })
        if column_profile["profile_result_json"].get("distinct_count") != 2:
            raise AssertionError("目录字段 distinct 探查结果不正确")
        selected_recommendation = _post_json(client, f"{base}/source-recommendations/{catalog_recommendation['id']}/adopt", {})
        scenario_lineage = selected_recommendation["lineage"]

        sensitive_field = _post_json(client, f"{base}/fields", {"project_id": project_id, "target_table_id": field["target_table_id"], "field_code": "CUSTOMER_NAME", "field_name": "客户姓名"})
        sensitive_recommendations = _post_json(client, f"{base}/target-fields/{sensitive_field['id']}/scenarios/{debit_scenario['id']}/recommend-sources", {})
        sensitive_catalog = next(item for item in sensitive_recommendations["recommendations"] if item.get("catalog_column_id") and item.get("recommended_field_name") == "customer_name")
        _post_json(client, f"{base}/source-recommendations/{sensitive_catalog['id']}/select", {})
        sensitive_profile = _post_json(client, f"{base}/catalog/columns/{sensitive_catalog['catalog_column_id']}/profile", {"target_field_id": sensitive_field["id"], "scenario_id": debit_scenario["id"], "source_recommendation_id": sensitive_catalog["id"], "metrics": ["distinct_count", "top_values", "min_max"]})
        if sensitive_profile["profile_result_json"].get("top_values"):
            raise AssertionError("敏感字段不应返回 top values")

        manual_business = "人工确认：借记卡场景证件类型按有效借记卡客户业务定义维护。"
        _put_json(client, f"{base}/scenario-business-mappings/{scenario_business['id']}", {"final_content": manual_business})
        generated_business = _post_json(client, f"{base}/scenario-business-mappings/{scenario_business['id']}/generate-draft", {})
        if generated_business["final_content"] != manual_business:
            raise AssertionError("AI 场景业务草稿覆盖了人工 final_content")
        adopted_business = _post_json(client, f"{base}/scenario-business-mappings/{scenario_business['id']}/adopt-ai-draft", {})
        _post_json(client, f"{base}/mappings/scenario_business/{scenario_business['id']}/evidence", {
            "evidence_type": "manual_note", "source_name": "Smoke 脱敏业务访谈记录",
            "evidence_summary": "业务部门确认场景业务口径。",
        })
        confirmed_business = _post_json(client, f"{base}/scenario-business-mappings/{scenario_business['id']}/confirm", {"confirmed_by": "smoke"})

        manual_technical = "人工确认：来源为 ECIF.ecif_customer.cert_type，按借记卡有效客户范围取值。"
        _put_json(client, f"{base}/scenario-technical-lineages/{scenario_lineage['id']}", {"final_content": manual_technical})
        generated_lineage = _post_json(client, f"{base}/scenario-technical-lineages/{scenario_lineage['id']}/generate-draft", {})
        if generated_lineage["final_content"] != manual_technical:
            raise AssertionError("AI 场景技术草稿覆盖了人工 final_content")
        if "安全探查摘要" not in generated_lineage["ai_generated_content"]:
            raise AssertionError("AI 场景技术草稿未引用目录探查摘要")
        adopted_lineage = _post_json(client, f"{base}/scenario-technical-lineages/{scenario_lineage['id']}/adopt-ai-draft", {})
        _post_json(client, f"{base}/mappings/scenario_technical/{scenario_lineage['id']}/evidence", {
            "evidence_type": "manual_note", "source_name": "Smoke 脱敏技术访谈记录",
            "evidence_summary": "科技部门确认场景技术溯源。",
        })
        confirmed_lineage = _post_json(client, f"{base}/scenario-technical-lineages/{scenario_lineage['id']}/confirm", {"confirmed_by": "smoke"})
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

        excel_export = client.get(f"{base}/projects/{project_id}/export/traceability-workbook")
        excel_export.raise_for_status()
        exported_workbook = load_workbook(BytesIO(excel_export.content), data_only=True)
        exported_sheet = exported_workbook["业务口径及技术溯源"]
        export_headers = {
            str(exported_sheet.cell(row, column).value or "")
            for row in (1, 2)
            for column in range(1, exported_sheet.max_column + 1)
        }
        required_excel_headers = {
            "数据项编码", "业务口径-借记卡", "溯源-借记卡", "来源系统", "来源表英文名",
            "来源字段英文名", "处理逻辑", "技术口径确认人",
        }
        if missing := required_excel_headers - export_headers:
            raise AssertionError(f"导出 Excel 缺少表头: {sorted(missing)}")
        current_group = ""
        debit_source_columns: dict[str, int] = {}
        for column in range(1, exported_sheet.max_column + 1):
            group_value = str(exported_sheet.cell(1, column).value or "")
            if group_value:
                current_group = group_value
            child_header = str(exported_sheet.cell(2, column).value or "")
            if current_group == "溯源-借记卡" and child_header in {"来源表英文名", "来源字段英文名"}:
                debit_source_columns[child_header] = column
        exported_field_row = next(
            row for row in range(3, exported_sheet.max_row + 1)
            if str(exported_sheet.cell(row, 1).value or "") == "CERT_TYPE"
        )
        exported_source_table = exported_sheet.cell(exported_field_row, debit_source_columns["来源表英文名"]).value
        exported_source_field = exported_sheet.cell(exported_field_row, debit_source_columns["来源字段英文名"]).value
        if exported_source_table != "ecif_customer" or exported_source_field != "cert_type":
            raise AssertionError(
                f"导出 Excel 未写入已采用目录来源: {exported_source_table}.{exported_source_field}"
            )

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
            "traceability_template_status": traceability_template["parse_status"],
            "traceability_preview_rows": len(traceability_preview["results"][0]["parsed_rows_json"]),
            "traceability_apply": traceability_apply,
            "scenario_codes": [item["scenario_code"] for item in scenarios],
            "recommendation_top_score": source_recommendations["recommendations"][0]["score"],
            "metadata_sync_status": metadata_sync["status"],
            "catalog_table_count": catalog_tables["total"],
            "catalog_source_field_id": catalog_source_import["source_field_id"],
            "column_profile_status": column_profile["status"],
            "column_profile_null_rate": column_profile["profile_result_json"].get("null_rate"),
            "sensitive_profile_top_values": sensitive_profile["profile_result_json"].get("top_values"),
            "selected_recommendation_id": selected_recommendation["recommendation"]["id"],
            "scenario_business_confirm_status": confirmed_business["business_confirm_status"],
            "scenario_technical_confirm_status": confirmed_lineage["tech_confirm_status"],
            "adopted_business_chars": len(adopted_business["final_content"]),
            "adopted_lineage_chars": len(adopted_lineage["final_content"]),
            "export_excel_bytes": len(excel_export.content),
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


def _write_traceability_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "客户信息场景口径"
    sheet["A1"] = "脱敏模拟业务口径及技术溯源表"
    fixed_headers = [
        "数据项编码", "数据项名称", "数据类别", "数据格式", "字段业务定义（监管原始口径）",
        "字段业务定义（监管定义细化）", "报表名称", "字段名称", "EAST口径", "字段业务定义（行内）", "备注",
    ]
    for column, title in enumerate(fixed_headers, start=1):
        sheet.cell(2, column, title)
        sheet.merge_cells(start_row=2, start_column=column, end_row=3, end_column=column)
    business_headers = ["字段业务定义", "源系统截图", "源系统改造", "外部数据", "手工补录", "业务口径确认人", "备注"]
    technical_headers = [
        "来源系统", "来源库", "来源schema", "来源表英文名", "来源表中文名", "来源字段英文名",
        "来源字段中文名", "处理逻辑", "处理逻辑类型", "技术口径确认人", "备注",
    ]
    column = 12
    for scenario_name, source_system in [("借记卡", "借记卡系统"), ("信用卡", "信用卡系统"), ("贷款产品", "信贷系统")]:
        column = _write_group(sheet, column, f"业务口径-{scenario_name}", business_headers)
        column = _write_group(sheet, column, f"溯源-{scenario_name}", technical_headers)
    rows = [
        ["CERT_TYPE", "客户证件类型", "基础信息", "VARCHAR(20)", "客户身份证件类型", "按产品场景确认客户证件类型", "客户信息表", "客户证件类型", "EAST_CERT_TYPE", "行内证件类型", "脱敏模拟"],
        ["CUSTOMER_ID", "客户编号", "基础信息", "VARCHAR(64)", "客户唯一编号", "按产品场景确认客户范围", "客户信息表", "客户编号", "EAST_CUSTOMER_ID", "行内客户编号", "脱敏模拟"],
    ]
    for row_number, fixed_values in enumerate(rows, start=4):
        for fixed_column, value in enumerate(fixed_values, start=1):
            sheet.cell(row_number, fixed_column, value)
        group_column = 12
        for scenario_name, source_system in [("借记卡", "借记卡系统"), ("信用卡", "信用卡系统"), ("贷款产品", "信贷系统")]:
            field_code = fixed_values[0]
            _write_values(sheet, row_number, group_column, [f"{scenario_name}{fixed_values[1]}业务口径", "是", "否", "否", "否", f"{scenario_name}业务部门", "待确认"])
            group_column += len(business_headers)
            _write_values(sheet, row_number, group_column, [source_system, "DEMO_DB", "ODS", f"{scenario_name}_CUSTOMER", f"{scenario_name}客户表", field_code, fixed_values[1], "源字段直接取值", "direct", "信息科技部", "脱敏模拟"])
            group_column += len(technical_headers)
    workbook.save(path)


def _write_group(sheet, start_column: int, title: str, headers: list[str]) -> int:
    end_column = start_column + len(headers) - 1
    sheet.cell(2, start_column, title)
    sheet.merge_cells(start_row=2, start_column=start_column, end_row=2, end_column=end_column)
    for offset, header in enumerate(headers):
        sheet.cell(3, start_column + offset, header)
    return end_column + 1


def _write_values(sheet, row: int, start_column: int, values: list[str]) -> None:
    for offset, value in enumerate(values):
        sheet.cell(row, start_column + offset, value)


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


def _get_json(client: httpx.Client, url: str) -> dict | list[dict]:
    response = client.get(url)
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
