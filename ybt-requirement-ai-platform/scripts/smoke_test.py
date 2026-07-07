import json
import tempfile
from pathlib import Path

import httpx


def main() -> None:
    base = "http://127.0.0.1:8000/api"
    client = httpx.Client(timeout=60, trust_env=False)

    project = client.post(
        f"{base}/projects",
        json={
            "name": "验收测试项目",
            "bank_name": "示例银行",
            "description": "用于端到端 smoke test",
        },
    )
    project.raise_for_status()
    project_data = project.json()
    project_id = project_data["id"]

    table = client.post(
        f"{base}/target-tables",
        json={
            "project_id": project_id,
            "table_code": "YBT_CUST_INFO",
            "table_name": "一表通客户信息表",
            "description": "客户基础信息",
        },
    )
    table.raise_for_status()
    table_data = table.json()

    field = client.post(
        f"{base}/fields",
        json={
            "project_id": project_id,
            "target_table_id": table_data["id"],
            "field_code": "CERT_TYPE",
            "field_name": "客户证件类型",
            "field_type": "varchar(20)",
            "required_flag": True,
            "field_definition": "客户身份证件类型，需映射监管代码集。",
            "regulatory_description": "用于识别客户证件类别。",
        },
    )
    field.raise_for_status()
    field_data = field.json()

    doc_path = _write_temp_file(
        ".md",
        "# EAST历史口径\n客户证件类型来自 ECIF 客户主表 cert_type，需要按监管代码集转换，空值需人工确认。",
    )
    with doc_path.open("rb") as file:
        document = client.post(
            f"{base}/documents/upload",
            data={"project_id": str(project_id), "source_type": "EAST口径"},
            files={"file": ("east_history.md", file, "text/markdown")},
        )
    document.raise_for_status()

    documents = client.get(f"{base}/documents", params={"project_id": project_id})
    documents.raise_for_status()

    sql_path = _write_temp_file(
        ".sql",
        """
select c.customer_id, c.cert_type, l.loan_no
from ecif_customer c
join loan_contract l on c.customer_id = l.customer_id
where c.status = 'A' and l.balance > 0
""",
    )
    with sql_path.open("rb") as file:
        sql_file = client.post(
            f"{base}/sql-files/upload",
            data={"project_id": str(project_id)},
            files={"file": ("ecif_customer.sql", file, "application/sql")},
        )
    sql_file.raise_for_status()
    sql_data = sql_file.json()

    retrieval = client.post(
        f"{base}/retrieval/search",
        json={
            "project_id": project_id,
            "query": "客户证件类型 EAST ECIF cert_type",
            "top_k": 5,
            "filters": {"source_type": ["EAST口径"]},
        },
    )
    retrieval.raise_for_status()
    retrieval_data = retrieval.json()

    mapping = client.post(f"{base}/fields/{field_data['id']}/generate-mapping", json={})
    mapping.raise_for_status()
    mapping_data = mapping.json()
    draft = mapping_data["draft"]

    reviewed = client.patch(
        f"{base}/fields/drafts/{draft['id']}/review",
        json={"review_status": "approved", "final_content": draft.get("final_content")},
    )
    reviewed.raise_for_status()
    reviewed_data = reviewed.json()

    print(
        json.dumps(
            {
                "project_id": project_id,
                "table_id": table_data["id"],
                "field_id": field_data["id"],
                "document_count": len(documents.json()),
                "sql_parse_success": sql_data["parse_result"]["parsed_success"],
                "source_tables": sql_data["parse_result"]["source_tables_json"],
                "selected_fields": sql_data["parse_result"]["selected_fields_json"],
                "retrieval_count": len(retrieval_data["results"]),
                "draft_id": draft["id"],
                "evidence_count": len(draft["evidences"]),
                "review_status": reviewed_data["review_status"],
                "confidence_level": draft["confidence_level"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_temp_file(suffix: str, content: str) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as file:
        file.write(content)
        return Path(file.name)


if __name__ == "__main__":
    main()
