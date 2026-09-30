from types import SimpleNamespace

import pytest

from app.models import CatalogColumn, TargetField
from app.services.ai_skills.field_candidates import lexical_score, recall_score
from app.services.ai_skills.field_vocabulary import field_concepts
from test_ai_skill_control import control_env
from test_ai_skill_field_candidates import seeded, proposal


@pytest.mark.parametrize("query,expected,decoy", [
    ("客户证件类型", "cert_type", "cert_no"),
    ("客户证件号码", "cert_no", "cert_type"),
    ("账户余额", "balance_amt", "imbalance"),
    ("执行利率", "interest_rate", "interest"),
    ("借据号", "due_bill_no", "due_date"),
    ("合同编号", "contract_no", "subcontract_no"),
    ("cert_type", "证件类型", "证件号码"),
])
def test_fixed_cross_language_candidates(query, expected, decoy):
    table = SimpleNamespace(table_name="t", table_comment=None)
    wanted = SimpleNamespace(column_name=expected, column_comment=None)
    other = SimpleNamespace(column_name=decoy, column_comment=None)
    score, concepts = recall_score(query, wanted, table)
    assert concepts
    assert score > lexical_score(query, wanted, table)
    assert score > recall_score(query, other, table)[0]


@pytest.mark.parametrize("text", ["imbalance", "subcontract_no", "cert_typewriter", "interest_rates", "forecast", "110400", "逾期贷款", "不良贷款"])
def test_concepts_do_not_infer_substrings_or_broad_business_equivalence(text):
    assert field_concepts(text) == set()


def test_repeated_terms_do_not_inflate_concept_score():
    column = SimpleNamespace(column_name="cert_type", column_comment=None)
    table = SimpleNamespace(table_name="t", table_comment=None)
    assert recall_score("证件类型", column, table)[0] == recall_score("证件类型 " * 10, column, table)[0]


@pytest.mark.parametrize("query,wanted,decoy", [
    ("balance", "balance_amt", "imbalance"),
    ("cert_type", "cert_type", "cert_typewriter"),
    ("contract_no", "contract_no", "subcontract_no"),
])
def test_english_identifiers_prefer_concept_boundaries(query, wanted, decoy):
    table = SimpleNamespace(table_name="t", table_comment=None)
    def score(name):
        return recall_score(query, SimpleNamespace(column_name=name, column_comment=None), table)[0]
    assert score(wanted) > score(decoy)


def test_real_catalog_cross_language_ranking_and_version_invalidation(control_env, monkeypatch):
    query, ids = seeded(control_env)
    client, factory, _, _, _ = control_env
    with factory() as db:
        target = db.get(TargetField, query["target_field_id"])
        target.field_code = "F001"
        target.field_name = "客户证件类型"
        column = db.get(CatalogColumn, ids["column"])
        column.column_name = "cert_type"
        column.column_comment = None
        db.commit()
    response = client.post("/ai-skills/field-candidates", json=query)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["candidates"][0]["column_name"] == "cert_type"
    assert "字段概念匹配：证件类型" in result["candidates"][0]["rationale"]
    assert result["writes_mapping"] is False
    assert result["execution_metadata"]["execution_kind"] == "deterministic"
    from app.services.ai_skills import field_candidates
    monkeypatch.setattr(field_candidates, "VOCABULARY_VERSION", "next-version")
    stale = client.post("/ai-skills/field-candidates/validate-ranking", json=proposal(query, result))
    assert stale.status_code == 409
