from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from product_5_1_common import (
    DEFAULT_RUNTIME_ROOT,
    DEMO_PROJECT_NAME,
    SCENARIOS,
    SEMANTIC_CONCEPTS,
    SOURCE_DATABASES,
    TARGET_COLUMN_BY_CODE,
    TARGET_TABLE_CODE,
    TARGET_TABLE_NAME,
    parse_regulatory_workbook,
    write_json,
)


FIELD_SEMANTICS = {
    "E010001": "PRODUCT_IDENTIFIER",
    "E010002": "REPORTING_INSTITUTION",
    "E010003": "PRODUCT",
    "E010004": "PRODUCT_IDENTIFIER",
    "E010005": "ACCOUNTING_SUBJECT_TYPE",
    "E010007": "PRODUCT_CATEGORY",
    "E010008": "PROPRIETARY_PRODUCT_FLAG",
    "E010009": "CURRENCY",
    "E010010": "PRODUCT_TERM",
    "E010011": "PRODUCT_LIFECYCLE",
    "E010012": "PRODUCT_LIFECYCLE",
    "E010013": "PRODUCT_ISSUE",
    "E010014": "INTEREST_RATE_TYPE",
    "E010015": "PRODUCT_STATUS",
    "E010018": "AGENCY_INSTITUTION",
    "E010016": "PRODUCT",
    "E010017": "PRODUCT_LIFECYCLE",
}

FIELD_SCENARIOS = {
    "E010005": "CORPORATE_OVERDRAFT",
    "E010007": "BANK_CARD",
    "E010008": "AGENCY_BUSINESS",
    "E010010": "BOND",
    "E010012": "BOND",
    "E010013": "WEALTH",
    "E010014": "WEALTH",
    "E010018": "AGENCY_BUSINESS",
}

SOURCE_SYSTEM_LABELS = {
    "product_center": ("PRODUCT_CENTER", "企业级产品中心"),
    "core_deposit": ("CORE_DEPOSIT", "核心存款系统"),
    "credit_loan": ("CREDIT_LOAN", "信贷系统"),
    "wealth_agency": ("WEALTH_AGENCY", "理财与代销系统"),
    "treasury_market": ("TREASURY_MARKET", "金融市场系统"),
    "reference": ("REFERENCE_DATA", "机构与公共参考数据"),
}


class Api:
    def __init__(
        self,
        base_url: str,
        timeout: float = 120,
        *,
        transport: httpx.BaseTransport | None = None,
        max_rate_limit_retries: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, trust_env=False, transport=transport)
        self.max_rate_limit_retries = max_rate_limit_retries

    def close(self) -> None:
        self.client.close()

    def authorize(self, token: str) -> None:
        self.client.headers["Authorization"] = f"Bearer {token}"

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200, 201),
        **kwargs: Any,
    ) -> Any:
        for attempt in range(self.max_rate_limit_retries + 1):
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
            if response.status_code != 429 or attempt >= self.max_rate_limit_retries:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(0.0, float(retry_after)) if retry_after is not None else None
            except ValueError:
                delay = None
            if delay is None:
                delay = min(2**attempt, 10)
            time.sleep(delay)
        if response.status_code not in expected:
            raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:1200]}")
        return response.json() if response.content else None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: dict | None = None, **kwargs: Any) -> Any:
        if payload is not None:
            kwargs["json"] = payload
        return self.request("POST", path, **kwargs)


def bootstrap_platform(
    api: Api,
    regulatory_xlsx: Path,
    runtime_root: Path,
    *,
    username: str,
    password: str,
    bootstrap_if_empty: bool = True,
) -> dict[str, Any]:
    if not (runtime_root / "build_summary.json").exists():
        raise RuntimeError("Demo runtime is missing. Run build_product_5_1_demo.py first.")
    regulatory = parse_regulatory_workbook(regulatory_xlsx)
    # Health is mounted both at the application root and below the configured
    # API prefix.  Using the prefixed route keeps URL joining deterministic.
    health = api.get("/health/ready")
    if bootstrap_if_empty:
        try:
            api.post(
                "/admin/bootstrap",
                {
                    "institution_code": "PLATFORM_DEMO",
                    "institution_name": "一表通演示平台",
                    "institution_type": "platform_operator",
                    "username": username,
                    "display_name": "产品5.1演示管理员",
                    "email": "product-5-1-admin@example.invalid",
                    "password": password,
                },
            )
        except RuntimeError as exc:
            if "409" not in str(exc):
                raise
    session = api.post("/auth/login", {"username": username, "password": password})
    api.authorize(session["access_token"])
    me = api.get("/auth/me")
    institution = _ensure_institution(api)
    project = _ensure_project(api, institution["id"])
    project_id = project["id"]
    datasources, sync_results = _ensure_datasources(api, project_id, runtime_root)
    catalog = _import_catalog_assets(api, project_id, datasources)
    target_table, target_fields = _ensure_target(api, project_id, regulatory)
    scenarios = _ensure_scenarios(api, project_id)
    knowledge = _ensure_regulatory_knowledge(api, project_id, regulatory_xlsx)
    concepts, bindings = _ensure_semantics(api, project_id, target_fields, catalog)
    mappings = _ensure_mapping_tasks(api, target_fields, catalog, scenarios)
    quality = _ensure_quality_expectations(api, project_id, target_fields)
    cycles = _ensure_reporting_cycles(api, project_id)
    lineage = _upload_baseline_sql(api, project_id)
    runtime = api.get("/ai-runtime/status")
    result = {
        "health": health,
        "authenticated_user": {"id": me["id"], "username": me["username"]},
        "institution": institution,
        "project": project,
        "datasources": datasources,
        "metadata_sync": sync_results,
        "catalog": catalog["summary"],
        "target_table": target_table,
        "target_field_count": len(target_fields),
        "scenario_count": len(scenarios),
        "knowledge": knowledge,
        "semantic_concept_count": len(concepts),
        "semantic_binding_count": len(bindings),
        "mapping_tasks": mappings,
        "quality_expectation_count": len(quality),
        "reporting_cycles": cycles,
        "lineage_ingestion": lineage,
        "ai_runtime": runtime,
        "llm_status": "BLOCKED_LLM_RUNTIME" if runtime["llm"].get("is_mock") else "READY_REAL_LLM",
        "embedding_status": "MOCK_INDEX" if runtime["embedding"].get("is_mock") else "READY_REAL_EMBEDDING",
    }
    write_json(runtime_root / "platform_bootstrap_summary.json", result)
    return result


def _ensure_institution(api: Api) -> dict:
    rows = api.get("/admin/institutions")
    existing = next((item for item in rows if item["institution_code"] == "YBT_DEMO_BANK"), None)
    return existing or api.post(
        "/admin/institutions",
        {
            "institution_code": "YBT_DEMO_BANK",
            "institution_name": "华东示例银行",
            "institution_type": "bank",
            "data_classification_policy_json": {"demo": True, "classification": "internal"},
        },
    )


def _ensure_project(api: Api, institution_id: int) -> dict:
    existing = next((item for item in api.get("/projects") if item["name"] == DEMO_PROJECT_NAME), None)
    return existing or api.post(
        "/projects",
        {
            "name": DEMO_PROJECT_NAME,
            "institution_id": institution_id,
            "bank_name": "华东示例银行",
            "description": "真实监管口径驱动的表5.1产品业务基本信息端到端演示",
            "governance_workflow_enabled": True,
            "confidentiality_level": "internal",
        },
    )


def _ensure_datasources(
    api: Api,
    project_id: int,
    runtime_root: Path,
) -> tuple[list[dict], list[dict]]:
    existing = {item["name"]: item for item in api.get(f"/projects/{project_id}/datasources")}
    rows: list[dict] = []
    sync_results: list[dict] = []
    for key, file_name in SOURCE_DATABASES.items():
        name = "p51_" + key
        item = existing.get(name)
        if item is None:
            item = api.post(
                f"/projects/{project_id}/datasources",
                {
                    "name": name,
                    "display_name": _datasource_label(key),
                    "description": f"Product 5.1 deterministic demo: {file_name}",
                    "db_type": "sqlite",
                    "database_name": str((runtime_root / file_name).resolve()),
                    "readonly_flag": True,
                    "enabled": True,
                },
            )
        connection = api.post(f"/datasources/{item['id']}/test", {})
        sync = api.post(
            f"/datasources/{item['id']}/metadata-sync",
            {"sync_mode": "full", "schema_names": [], "include_views": True},
        )
        rows.append(item)
        sync_results.append(
            {"datasource_id": item["id"], "name": name, "connection": connection, "sync": sync}
        )
    return rows, sync_results


def _datasource_label(key: str) -> str:
    labels = {
        "product_center": "产品中心",
        "core_deposit": "核心存款系统",
        "credit_loan": "信贷系统",
        "wealth_agency": "理财与代销系统",
        "treasury_market": "金融市场系统",
        "reference": "机构与公共参考数据",
        "regulatory_mart": "监管产品数据集市",
    }
    return labels[key]


def _import_catalog_assets(api: Api, project_id: int, datasources: list[dict]) -> dict:
    source_fields: dict[tuple[str, str, str], int] = {}
    mart_fields: dict[tuple[str, str], int] = {}
    table_count = 0
    column_count = 0
    for datasource in datasources:
        response = api.get(
            f"/projects/{project_id}/catalog/tables",
            params={"datasource_id": datasource["id"], "page_size": 200},
        )
        for table in response["items"]:
            table_count += 1
            is_mart = (
                datasource["name"] == "p51_regulatory_mart"
                and table["table_name"].startswith("mart_")
            )
            if is_mart:
                api.post(f"/catalog/tables/{table['id']}/import-as-mart-table", {})
            elif datasource["name"] != "p51_regulatory_mart":
                key = datasource["name"].removeprefix("p51_")
                code, label = SOURCE_SYSTEM_LABELS[key]
                api.post(
                    f"/catalog/tables/{table['id']}/import-as-source-table",
                    {"system_code": code, "system_name": label},
                )
            columns = api.get(
                f"/catalog/tables/{table['id']}/columns",
                params={"page_size": 200},
            )["items"]
            for column in columns:
                column_count += 1
                if is_mart:
                    imported = api.post(f"/catalog/columns/{column['id']}/import-as-mart-field", {})
                    mart_fields[(table["table_name"], column["column_name"])] = imported["mart_field_id"]
                elif datasource["name"] != "p51_regulatory_mart":
                    key = datasource["name"].removeprefix("p51_")
                    code, label = SOURCE_SYSTEM_LABELS[key]
                    imported = api.post(
                        f"/catalog/columns/{column['id']}/import-as-source-field",
                        {"system_code": code, "system_name": label},
                    )
                    source_fields[(key, table["table_name"], column["column_name"])] = imported[
                        "source_field_id"
                    ]
    return {
        "source_fields": source_fields,
        "mart_fields": mart_fields,
        "summary": {
            "catalog_table_count": table_count,
            "catalog_column_count": column_count,
            "imported_source_field_count": len(source_fields),
            "imported_mart_field_count": len(mart_fields),
        },
    }


def _ensure_target(
    api: Api,
    project_id: int,
    regulatory: dict,
) -> tuple[dict, dict[str, dict]]:
    tables = api.get("/target-tables", params={"project_id": project_id})
    table = next((item for item in tables if item["table_code"] == TARGET_TABLE_CODE), None)
    if table is None:
        table = api.post(
            "/target-tables",
            {
                "project_id": project_id,
                "table_code": TARGET_TABLE_CODE,
                "table_name": TARGET_TABLE_NAME,
                "description": regulatory["collection_scope"],
            },
        )
    existing = {
        item["field_code"]: item
        for item in api.get(
            "/fields",
            params={"project_id": project_id, "target_table_id": table["id"]},
        )
    }
    for field in regulatory["fields"]:
        if field["field_code"] in existing:
            continue
        existing[field["field_code"]] = api.post(
            "/fields",
            {
                "project_id": project_id,
                "target_table_id": table["id"],
                "field_code": field["field_code"],
                "field_name": field["field_name"],
                "field_type": field["data_format"],
                "required_flag": field["field_code"]
                not in {"E010013", "E010014", "E010018", "E010016"},
                "field_definition": field["regulatory_original_definition"],
                "regulatory_description": field["regulatory_original_definition"],
                "data_category": field["data_category"],
                "data_format": field["data_format"],
                "regulatory_original_definition": field["regulatory_original_definition"],
                "regulatory_refined_definition": field["regulatory_refined_definition"],
                "report_name": TARGET_TABLE_NAME,
                "report_field_name": field["field_name"],
                "internal_definition": (
                    f"Bank Internal Interpretation: 物理字段 {field['physical_column']}，"
                    "最终以人工审核内容为准。"
                ),
            },
        )
    return table, existing


def _ensure_scenarios(api: Api, project_id: int) -> dict[str, dict]:
    existing = {
        item["scenario_code"]: item for item in api.get(f"/projects/{project_id}/scenarios")
    }
    for order, (code, name, kind) in enumerate(SCENARIOS, 1):
        if code not in existing:
            existing[code] = api.post(
                f"/projects/{project_id}/scenarios",
                {
                    "scenario_code": code,
                    "scenario_name": name,
                    "scenario_type": kind,
                    "description": f"表5.1 {name}监管填报场景",
                    "business_owner": "产品管理部",
                    "tech_owner": "数据平台部",
                    "sort_order": order,
                },
            )
    return existing


def _ensure_regulatory_knowledge(api: Api, project_id: int, path: Path) -> dict:
    existing = api.get(f"/projects/{project_id}/knowledge/documents")
    found = next((item for item in existing if item["file_name"] == path.name), None)
    if found:
        return found
    with path.open("rb") as handle:
        return api.request(
            "POST",
            f"/projects/{project_id}/knowledge/documents/upload",
            files={
                "file": (
                    path.name,
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={
                "knowledge_type": "regulatory_policy",
                "knowledge_scope": "project",
                "confidentiality_level": "internal",
                "change_note": "表5.1真实监管原始口径及监管定义细化",
            },
        )


def _ensure_semantics(
    api: Api,
    project_id: int,
    target_fields: dict[str, dict],
    catalog: dict,
) -> tuple[dict[str, dict], list[dict]]:
    concepts = {
        item["concept_code"]: item
        for item in api.get(f"/projects/{project_id}/semantic-concepts", params={"limit": 500})
    }
    for code, name, kind, definition in SEMANTIC_CONCEPTS:
        if code not in concepts:
            concepts[code] = api.post(
                f"/projects/{project_id}/semantic-concepts",
                {
                    "concept_type": kind,
                    "concept_code": code,
                    "concept_name": name,
                    "definition": definition,
                    "description": "Product 5.1 Demo governed semantic",
                    "aliases_json": [name, code.lower()],
                    "business_domain": "产品监管",
                    "owner_department": "数据治理部",
                    "status": "ai_suggested",
                    "confidence_level": "high",
                    "source_type": "regulatory_excel",
                },
            )
    existing = api.get(f"/projects/{project_id}/semantic-bindings", params={"limit": 1000})
    keys = {
        (binding["semantic_concept_id"], binding["entity_type"], binding["entity_id"])
        for binding in existing
    }
    bindings = list(existing)

    def bind(concept_code: str, entity_type: str, entity_id: int, source_type: str) -> None:
        key = (concepts[concept_code]["id"], entity_type, entity_id)
        if key in keys:
            return
        bindings.append(
            api.post(
                f"/projects/{project_id}/semantic-bindings",
                {
                    "semantic_concept_id": key[0],
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "binding_type": "describes",
                    "confidence_level": "high",
                    "confidence_score": 0.95,
                    "status": "ai_suggested",
                    "source_type": source_type,
                },
            )
        )
        keys.add(key)

    for field_code, field in target_fields.items():
        bind(FIELD_SEMANTICS[field_code], "target_field", field["id"], "regulatory_excel")
    for (table, column), field_id in catalog["mart_fields"].items():
        matching = next((code for code, name in TARGET_COLUMN_BY_CODE.items() if name == column), None)
        if matching:
            bind(FIELD_SEMANTICS[matching], "mart_field", field_id, "catalog_import")
    source_name_to_concept = {
        "product_id_internal": "PRODUCT_IDENTIFIER",
        "product_code": "PRODUCT_IDENTIFIER",
        "product_name": "PRODUCT",
        "currency_code": "CURRENCY",
        "status_code": "PRODUCT_STATUS",
        "product_status": "PRODUCT_STATUS",
        "interest_rate_type": "INTEREST_RATE_TYPE",
        "rate_mode": "INTEREST_RATE_TYPE",
        "institution_id": "REPORTING_INSTITUTION",
        "issue_no": "PRODUCT_ISSUE",
        "maturity_date": "PRODUCT_LIFECYCLE",
        "launch_date": "PRODUCT_LIFECYCLE",
        "proprietary_flag": "PROPRIETARY_PRODUCT_FLAG",
        "issuer_name": "AGENCY_INSTITUTION",
    }
    for (_, _, column), field_id in catalog["source_fields"].items():
        concept = source_name_to_concept.get(column)
        if concept:
            bind(concept, "source_field", field_id, "catalog_import")
    return concepts, bindings


def _ensure_mapping_tasks(
    api: Api,
    target_fields: dict[str, dict],
    catalog: dict,
    scenarios: dict[str, dict],
) -> dict:
    mart_fields = catalog["mart_fields"]
    source_mapping_ids: list[int] = []
    target_mapping_ids: list[int] = []
    scenario_tasks: list[dict] = []
    for code, column in TARGET_COLUMN_BY_CODE.items():
        mart_id = mart_fields.get(("mart_product_master", column)) or mart_fields.get(
            ("mart_product_regulatory_classification", column)
        )
        if mart_id:
            current = api.get(f"/mart-fields/{mart_id}/source-to-mart-mappings")
            mapping = current[0] if current else api.post(
                f"/mart-fields/{mart_id}/source-to-mart-mappings",
                {
                    "mapping_name": f"{code} Source→Mart Agent Task",
                    "confidence_level": "medium",
                    "created_by": "demo-bootstrap",
                },
            )
            source_mapping_ids.append(mapping["id"])
        target_field = target_fields[code]
        current = api.get(f"/target-fields/{target_field['id']}/mart-to-ybt-mappings")
        mapping = current[0] if current else api.post(
            f"/target-fields/{target_field['id']}/mart-to-ybt-mappings",
            {
                "mapping_name": f"{code} Mart→YBT Agent Task",
                "confidence_level": "medium",
                "created_by": "demo-bootstrap",
            },
        )
        target_mapping_ids.append(mapping["id"])
        scenario_code = FIELD_SCENARIOS.get(code, "CORPORATE_DEPOSIT")
        scenario = scenarios[scenario_code]
        business_rows = api.get(f"/target-fields/{target_field['id']}/scenario-business-mappings")
        business = next(
            (item for item in business_rows if item["scenario_id"] == scenario["id"]),
            None,
        ) or api.post(
            f"/target-fields/{target_field['id']}/scenarios/{scenario['id']}/business-mapping",
            {"business_owner": "产品管理部", "created_by": "demo-bootstrap"},
        )
        technical_rows = api.get(
            f"/target-fields/{target_field['id']}/scenario-technical-lineages"
        )
        technical = next(
            (item for item in technical_rows if item["scenario_id"] == scenario["id"]),
            None,
        ) or api.post(
            f"/target-fields/{target_field['id']}/scenarios/{scenario['id']}/technical-lineage",
            {
                "business_mapping_id": business["id"],
                "tech_owner": "数据平台部",
                "created_by": "demo-bootstrap",
            },
        )
        scenario_tasks.append(
            {
                "field_code": code,
                "scenario_code": scenario_code,
                "business_mapping_id": business["id"],
                "technical_lineage_id": technical["id"],
            }
        )
    return {
        "source_to_mart_ids": source_mapping_ids,
        "mart_to_ybt_ids": target_mapping_ids,
        "scenario_tasks": scenario_tasks,
    }


def _ensure_quality_expectations(
    api: Api,
    project_id: int,
    target_fields: dict[str, dict],
) -> list[dict]:
    spec_path = (
        Path(__file__).resolve().parents[2]
        / "demo"
        / "product_5_1"
        / "expected"
        / "data_quality_expectations.json"
    )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    existing = {
        item["rule_code"]: item
        for item in api.get(f"/projects/{project_id}/quality-expectations")
    }
    result = []
    for rule in spec["expectations"]:
        item = existing.get(rule["rule_code"])
        if item is None:
            item = api.post(
                f"/projects/{project_id}/quality-expectations",
                {
                    "rule_code": rule["rule_code"],
                    "rule_name": rule["rule_name"],
                    "description": (
                        "Product 5.1 regulatory expectation; this is configuration, "
                        "not an execution result."
                    ),
                    "rule_type": rule["rule_type"],
                    "expression": rule.get("expression"),
                    "parameters_json": rule.get("parameters", {}),
                    "severity": rule["severity"],
                    "status": "draft",
                    "source_type": "regulatory_excel",
                    "confidence_level": "high",
                    "bindings": [
                        {
                            "scope_type": "requirement",
                            "entity_type": "target_field",
                            "entity_id": target_fields[rule["field_code"]]["id"],
                            "configuration_json": {"field_code": rule["field_code"]},
                        }
                    ],
                },
            )
        result.append(item)
    return result


def _ensure_reporting_cycles(api: Api, project_id: int) -> list[dict]:
    existing = {
        item["cycle_code"]: item
        for item in api.get(f"/projects/{project_id}/reporting-cycles")
    }
    result = []
    definitions = [
        (
            "2026-07",
            "2026年7月监管周期",
            "2026-07-01T00:00:00+08:00",
            "2026-08-01T00:00:00+08:00",
        ),
        (
            "2026-08",
            "2026年8月监管周期",
            "2026-08-01T00:00:00+08:00",
            "2026-09-01T00:00:00+08:00",
        ),
    ]
    for code, name, start, end in definitions:
        item = existing.get(code) or api.post(
            f"/projects/{project_id}/reporting-cycles",
            {
                "cycle_code": code,
                "cycle_name": name,
                "reporting_type": "regular",
                "period_start": start,
                "period_end": end,
                "data_cutoff_at": end,
                "submission_deadline": end,
                "status": "preparing",
                "owner_department": "监管报送部",
                "description": "由同一确定性数据集的不同真实状态形成，不是伪造历史。",
            },
        )
        result.append(item)
    return result


def _upload_baseline_sql(api: Api, project_id: int) -> list[dict]:
    root = Path(__file__).resolve().parents[2] / "demo" / "product_5_1" / "sql"
    uploads = []
    entries = [
        (
            root / "source_to_mart" / "build_mart_product.sql",
            "product_5_1/source_to_mart/build_mart_product.sql",
        ),
        (
            root / "mart_to_regulatory" / "build_ybt_5_1_v1.sql",
            "product_5_1/mart_to_regulatory/build_ybt_5_1.sql",
        ),
    ]
    existing = {item["relative_path"]: item for item in api.get(f"/projects/{project_id}/scripts")}
    for path, relative in entries:
        if relative in existing:
            uploads.append({"script_file_id": existing[relative]["id"], "deduplicated": True})
            continue
        with path.open("rb") as handle:
            uploads.append(
                api.request(
                    "POST",
                    f"/projects/{project_id}/scripts/upload",
                    files={"file": (Path(relative).name, handle, "text/plain")},
                    data={
                        "relative_path": relative,
                        "dialect": "sqlite",
                        "change_note": "Product 5.1 deterministic baseline",
                    },
                )
            )
    return uploads


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Product 5.1 demo through existing platform APIs"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("PRODUCT_5_1_BASE_URL", "http://127.0.0.1:8000/api"),
    )
    parser.add_argument(
        "--username",
        default=os.getenv("PRODUCT_5_1_ADMIN_USERNAME", "product_5_1_admin"),
    )
    parser.add_argument("--password", default=os.getenv("PRODUCT_5_1_ADMIN_PASSWORD"))
    parser.add_argument(
        "--regulatory-xlsx",
        type=Path,
        default=Path.home() / "Desktop" / "5_1产品表 - 副本.xlsx",
    )
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--no-bootstrap", action="store_true")
    args = parser.parse_args()
    if not args.password:
        raise SystemExit(
            "Set PRODUCT_5_1_ADMIN_PASSWORD or pass --password (minimum 12 characters)."
        )
    api = Api(args.base_url)
    try:
        print(
            json.dumps(
                bootstrap_platform(
                    api,
                    args.regulatory_xlsx,
                    args.runtime_root,
                    username=args.username,
                    password=args.password,
                    bootstrap_if_empty=not args.no_bootstrap,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        api.close()


if __name__ == "__main__":
    main()
