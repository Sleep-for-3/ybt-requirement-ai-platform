from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


def test_product_scenario_crud_and_project_code_uniqueness() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "场景口径项目"})
        scenario = _post(
            client,
            f"/api/projects/{project['id']}/scenarios",
            {
                "scenario_code": "DEBIT_CARD",
                "scenario_name": "借记卡",
                "scenario_type": "product",
                "business_owner": "银行卡部",
                "tech_owner": "信息科技部",
                "sort_order": 10,
            },
        )

        assert scenario["scenario_code"] == "DEBIT_CARD"
        assert scenario["enabled"] is True
        listed = _get(client, f"/api/projects/{project['id']}/scenarios")
        assert [item["scenario_name"] for item in listed] == ["借记卡"]

        updated = _put(client, f"/api/scenarios/{scenario['id']}", {"scenario_name": "借记卡业务", "enabled": False})
        assert updated["scenario_name"] == "借记卡业务"
        assert updated["enabled"] is False

        duplicate = client.post(
            f"/api/projects/{project['id']}/scenarios",
            json={"scenario_code": "DEBIT_CARD", "scenario_name": "重复场景"},
        )
        assert duplicate.status_code == 409

        deleted = client.delete(f"/api/scenarios/{scenario['id']}")
        deleted.raise_for_status()
        assert deleted.json() == {"status": "deleted"}


def test_scenario_mappings_adopt_drafts_quality_checks_and_knowledge_search() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "字段场景项目"})
        table = _post(
            client,
            "/api/target-tables",
            {"project_id": project["id"], "table_code": "YBT_CARD", "table_name": "银行卡信息"},
        )
        field = _post(
            client,
            "/api/fields",
            {
                "project_id": project["id"],
                "target_table_id": table["id"],
                "field_code": "CARD_PRODUCT_ID",
                "field_name": "卡产品编号",
                "field_definition": "银行卡产品唯一编号",
            },
        )
        scenario = _post(
            client,
            f"/api/projects/{project['id']}/scenarios",
            {"scenario_code": "DEBIT_CARD", "scenario_name": "借记卡"},
        )

        business = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/business-mapping",
            {"business_definition": "取借记卡产品编号", "business_owner": "银行卡部"},
        )
        lineage = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/technical-lineage",
            {
                "business_mapping_id": business["id"],
                "source_system_name": "借记卡系统",
                "source_table_english_name": "CPS_CARDPRODUCT",
                "source_field_english_name": "CARD_PRODUCT_ID",
                "processing_logic": "源字段直接取值",
                "processing_logic_type": "direct",
            },
        )
        assert business["business_confirm_status"] == "draft"
        assert lineage["processing_logic_type"] == "direct"

        business_with_draft = _put(
            client,
            f"/api/scenario-business-mappings/{business['id']}",
            {"final_content": "人工业务口径"},
        )
        generated_business = _post(client, f"/api/scenario-business-mappings/{business['id']}/generate-draft", {})
        adopted_business = _post(
            client,
            f"/api/scenario-business-mappings/{business['id']}/adopt-ai-draft",
            {},
        )
        assert business_with_draft["final_content"] == "人工业务口径"
        assert generated_business["final_content"] == "人工业务口径"
        assert generated_business["ai_generated_content"]
        assert adopted_business["final_content"] == generated_business["ai_generated_content"]

        lineage_with_draft = _put(
            client,
            f"/api/scenario-technical-lineages/{lineage['id']}",
            {"final_content": "人工技术口径"},
        )
        generated_lineage = _post(client, f"/api/scenario-technical-lineages/{lineage['id']}/generate-draft", {})
        adopted_lineage = _post(
            client,
            f"/api/scenario-technical-lineages/{lineage['id']}/adopt-ai-draft",
            {},
        )
        assert lineage_with_draft["final_content"] == "人工技术口径"
        assert generated_lineage["final_content"] == "人工技术口径"
        assert generated_lineage["ai_generated_content"]
        assert adopted_lineage["final_content"] == generated_lineage["ai_generated_content"]

        empty_business = _post(
            client,
            f"/api/target-fields/{field['id']}/scenarios/{scenario['id'] + 1}/business-mapping",
            {},
            expected_status=404,
        )
        assert empty_business["detail"] == "Scenario not found"

        confirmed_business = _post(client, f"/api/scenario-business-mappings/{business['id']}/confirm", {"confirmed_by": "tester"})
        confirmed_lineage = _post(client, f"/api/scenario-technical-lineages/{lineage['id']}/confirm", {"confirmed_by": "tester"})
        assert confirmed_business["business_confirm_status"] == "confirmed"
        assert confirmed_lineage["tech_confirm_status"] == "confirmed"

        knowledge = _post(
            client,
            f"/api/projects/{project['id']}/knowledge/items",
            {
                "knowledge_type": "historical_mapping",
                "target_table_code": "YBT_CARD",
                "target_field_code": "CARD_PRODUCT_ID",
                "target_field_name": "卡产品编号",
                "scenario_id": scenario["id"],
                "business_explanation": "历史确认从借记卡系统产品表取值",
                "source_document_name": "脱敏历史口径.xlsx",
                "source_sheet_name": "银行卡信息",
                "source_cell_range": "L3",
            },
        )
        search = _post(
            client,
            f"/api/projects/{project['id']}/knowledge/search",
            {"target_field_code": "CARD_PRODUCT_ID", "scenario_id": scenario["id"], "query": "借记卡", "top_k": 5},
        )
        assert knowledge["knowledge_type"] == "historical_mapping"
        assert search["items"][0]["id"] == knowledge["id"]
        assert search["items"][0]["score"] > 0


def test_source_recommendations_are_scored_explained_and_selected_explicitly() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "来源推荐项目"})
        table = _post(client, "/api/target-tables", {
            "project_id": project["id"], "table_code": "YBT_CARD", "table_name": "银行卡信息"
        })
        field = _post(client, "/api/fields", {
            "project_id": project["id"], "target_table_id": table["id"], "field_code": "CARD_PRODUCT_ID",
            "field_name": "卡产品编号", "field_definition": "银行卡产品唯一编号"
        })
        scenario = _post(client, f"/api/projects/{project['id']}/scenarios", {
            "scenario_code": "DEBIT_CARD", "scenario_name": "借记卡"
        })
        unrelated_system = _post(client, f"/api/projects/{project['id']}/business-systems", {
            "system_code": "OTHER", "system_name": "无关系统"
        })
        unrelated_table = _post(client, f"/api/business-systems/{unrelated_system['id']}/source-tables", {
            "table_code": "OTHER_TABLE", "table_name": "无关表"
        })
        _post(client, f"/api/source-tables/{unrelated_table['id']}/source-fields", {
            "field_code": "UNRELATED_VALUE", "field_name": "无关字段", "field_comment": "与卡产品无关"
        })
        card_system = _post(client, f"/api/projects/{project['id']}/business-systems", {
            "system_code": "DCPS", "system_name": "借记卡系统"
        })
        card_table = _post(client, f"/api/business-systems/{card_system['id']}/source-tables", {
            "table_code": "CPS_CARDPRODUCT", "table_name": "卡产品表", "schema_name": "ODS"
        })
        source = _post(client, f"/api/source-tables/{card_table['id']}/source-fields", {
            "field_code": "CARD_PRODUCT_ID", "field_name": "卡产品编号", "field_comment": "银行卡产品唯一编号"
        })
        _post(client, f"/api/projects/{project['id']}/knowledge/items", {
            "knowledge_type": "historical_mapping", "target_field_code": "CARD_PRODUCT_ID", "scenario_id": scenario["id"],
            "business_explanation": "借记卡场景历史来源为 CPS_CARDPRODUCT.CARD_PRODUCT_ID"
        })

        response = _post(client, f"/api/target-fields/{field['id']}/scenarios/{scenario['id']}/recommend-sources", {})
        top = response["recommendations"][0]
        assert top["recommended_field_name"] == source["field_code"]
        assert top["score"] > response["recommendations"][-1]["score"]
        assert top["recommend_reason"]
        assert top["evidence_summary"]
        assert top["selected_flag"] is False

        selected = _post(client, f"/api/source-recommendations/{top['id']}/select", {})
        assert selected["recommendation"]["selected_flag"] is True
        assert selected["lineage"]["source_system_name"] == "借记卡系统"
        assert selected["lineage"]["source_table_english_name"] == "CPS_CARDPRODUCT"
        assert selected["lineage"]["source_field_english_name"] == "CARD_PRODUCT_ID"
        assert selected["lineage"]["final_content"] is None


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def _post(client: TestClient, path: str, payload: dict, expected_status: int = 200) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code == expected_status, response.text
    return response.json()


def _put(client: TestClient, path: str, payload: dict) -> dict:
    response = client.put(path, json=payload)
    response.raise_for_status()
    return response.json()


def _get(client: TestClient, path: str) -> dict | list[dict]:
    response = client.get(path)
    response.raise_for_status()
    return response.json()
