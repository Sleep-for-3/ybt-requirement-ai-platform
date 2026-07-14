from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


def test_double_layer_mapping_end_to_end_api() -> None:
    with _client() as client:
        project = _post(
            client,
            "/api/projects",
            {"name": "双层口径项目", "bank_name": "示例银行", "description": "验证双层业务口径"},
        )
        table = _post(
            client,
            "/api/target-tables",
            {"project_id": project["id"], "table_code": "YBT_CUSTOMER", "table_name": "客户信息表"},
        )
        target_field = _post(
            client,
            "/api/fields",
            {
                "project_id": project["id"],
                "target_table_id": table["id"],
                "field_code": "CERT_TYPE",
                "field_name": "客户证件类型",
                "field_type": "varchar(20)",
                "required_flag": True,
                "field_definition": "客户身份证件类型",
                "regulatory_description": "按一表通证件类型代码集报送",
            },
        )

        business_system = _post(
            client,
            f"/api/projects/{project['id']}/business-systems",
            {"system_code": "ECIF", "system_name": "客户信息系统", "owner_department": "数据管理部", "enabled": True},
        )
        source_table = _post(
            client,
            f"/api/business-systems/{business_system['id']}/source-tables",
            {"table_code": "ecif_customer", "table_name": "客户基本信息表", "table_comment": "ECIF 客户主表"},
        )
        source_field = _post(
            client,
            f"/api/source-tables/{source_table['id']}/source-fields",
            {"field_code": "cert_type", "field_name": "证件类型", "field_type": "varchar(20)", "field_comment": "客户证件类型"},
        )
        mart_table = _post(
            client,
            f"/api/projects/{project['id']}/mart-tables",
            {
                "table_code": "mart_customer",
                "table_name": "监管客户集市表",
                "subject_area": "客户",
                "table_comment": "监管报送客户主题",
                "is_existing": False,
            },
        )
        mart_field = _post(
            client,
            f"/api/mart-tables/{mart_table['id']}/mart-fields",
            {
                "field_code": "cert_type",
                "field_name": "客户证件类型",
                "field_type": "varchar(20)",
                "field_comment": "统一监管集市证件类型",
                "is_existing": False,
            },
        )

        source_to_mart = _post(
            client,
            f"/api/mart-fields/{mart_field['id']}/source-to-mart-mappings",
            {
                "mapping_name": "ECIF 证件类型入集市",
                "source_system_summary": "ECIF",
                "source_tables_summary": "ecif_customer",
                "source_fields_summary": "cert_type",
                "business_rule": "从 ECIF 客户基本信息取客户证件类型。",
            },
        )
        mart_to_ybt = _post(
            client,
            f"/api/target-fields/{target_field['id']}/mart-to-ybt-mappings",
            {
                "mart_field_id": mart_field["id"],
                "mapping_name": "监管集市证件类型到一表通",
                "mart_table_summary": "mart_customer",
                "mart_field_summary": "cert_type",
                "business_rule": "从监管客户集市表取证件类型并转换为一表通代码。",
            },
        )

        empty_approval = client.post(f"/api/source-to-mart-mappings/{source_to_mart['id']}/approve", json={"reviewed_by": "tester"})
        assert empty_approval.status_code == 400
        assert "final_content" in empty_approval.json()["detail"]

        source_evidence = _post(
            client,
            f"/api/mappings/source_to_mart/{source_to_mart['id']}/evidence",
            {
                "evidence_type": "source_field",
                "evidence_id": source_field["id"],
                "source_name": "ECIF.ecif_customer.cert_type",
                "location_text": "源字段",
                "quoted_content": "客户证件类型字段",
                "evidence_summary": "证明监管集市字段来源于 ECIF 证件类型。",
            },
        )
        ybt_evidence = _post(
            client,
            f"/api/mappings/mart_to_ybt/{mart_to_ybt['id']}/evidence",
            {
                "evidence_type": "target_field",
                "evidence_id": target_field["id"],
                "source_name": "一表通模板",
                "location_text": "YBT_CUSTOMER.CERT_TYPE",
                "quoted_content": "按一表通证件类型代码集报送",
                "evidence_summary": "证明一表通目标字段定义。",
            },
        )

        source_manual = "人工维护的业务系统到监管集市口径"
        ybt_manual = "人工维护的监管集市到一表通口径"
        _put(client, f"/api/source-to-mart-mappings/{source_to_mart['id']}", {"final_content": source_manual})
        _put(client, f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}", {"final_content": ybt_manual})
        source_draft = _post(client, f"/api/source-to-mart-mappings/{source_to_mart['id']}/generate-draft", {})
        ybt_draft = _post(client, f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}/generate-draft", {})

        assert source_draft["final_content"] == source_manual
        assert ybt_draft["final_content"] == ybt_manual
        assert "select " not in source_draft["ai_generated_content"].lower()
        assert "业务系统到监管集市" in source_draft["ai_generated_content"]
        assert "监管集市到一表通" in ybt_draft["ai_generated_content"]
        assert ybt_draft["mart_field_summary"]

        no_evidence_mapping = _post(
            client,
            f"/api/mart-fields/{mart_field['id']}/source-to-mart-mappings",
            {"final_content": "已有人工最终口径，但尚未绑定证据。"},
        )
        no_evidence_approval = client.post(
            f"/api/source-to-mart-mappings/{no_evidence_mapping['id']}/approve",
            json={"reviewed_by": "tester"},
        )
        assert no_evidence_approval.status_code == 400
        assert "evidence" in no_evidence_approval.json()["detail"].lower()

        source_adopted = _post(client, f"/api/source-to-mart-mappings/{source_to_mart['id']}/adopt-ai-draft", {})
        ybt_adopted = _post(client, f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}/adopt-ai-draft", {})
        assert source_adopted["final_content"] == source_adopted["ai_generated_content"]
        assert ybt_adopted["final_content"] == ybt_adopted["ai_generated_content"]

        source_saved = _put(
            client,
            f"/api/source-to-mart-mappings/{source_to_mart['id']}",
            {
                "final_content": "业务系统到监管集市：ECIF 客户证件类型进入 mart_customer.cert_type，空值列入待确认。",
                "open_questions": "请确认 ECIF 证件类型码值是否为最新监管代码集。",
            },
        )
        ybt_saved = _put(
            client,
            f"/api/mart-to-ybt-mappings/{mart_to_ybt['id']}",
            {
                "final_content": "监管集市到一表通：mart_customer.cert_type 映射到 CERT_TYPE，并按一表通代码集转换。",
                "open_questions": "请确认报送日期内有效客户口径。",
            },
        )

        source_version = _post(client, f"/api/source-to-mart-mappings/{source_saved['id']}/save-version", {"change_note": "人工确认"})
        ybt_version = _post(client, f"/api/mart-to-ybt-mappings/{ybt_saved['id']}/save-version", {"change_note": "人工确认"})
        source_approved = _post(client, f"/api/source-to-mart-mappings/{source_saved['id']}/approve", {"reviewed_by": "tester"})
        ybt_rejected = _post(client, f"/api/mart-to-ybt-mappings/{ybt_saved['id']}/reject", {"reviewed_by": "tester"})

        assert source_evidence["mapping_type"] == "source_to_mart"
        assert ybt_evidence["mapping_type"] == "mart_to_ybt"
        assert source_version["version_no"] == 1
        assert ybt_version["version_no"] == 1
        assert source_approved["mapping_status"] == "approved"
        assert ybt_rejected["mapping_status"] == "rejected"

        field_export = _get(client, f"/api/target-fields/{target_field['id']}/export/mapping-document?format=markdown")
        table_export = _get(client, f"/api/target-tables/{table['id']}/export/mapping-document?format=markdown")
        project_export = _get(client, f"/api/projects/{project['id']}/export/mapping-document?format=markdown")

        for exported in [field_export, table_export, project_export]:
            markdown = exported["content"]
            assert "一表通字段信息" in markdown
            assert "监管集市字段设计" in markdown
            assert "业务系统到监管集市取数口径" in markdown
            assert "监管集市到一表通取数口径" in markdown
            assert "参考依据" in markdown
            assert "待确认问题" in markdown
            assert "审核状态" in markdown


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def _put(client: TestClient, path: str, payload: dict) -> dict:
    response = client.put(path, json=payload)
    response.raise_for_status()
    return response.json()


def _get(client: TestClient, path: str) -> dict:
    response = client.get(path)
    response.raise_for_status()
    return response.json()
