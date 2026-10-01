"""Regression: the field-rerank whitelist ids are contract values, never raw strings to split.

Before this fix a ``catalog_field`` fact whose id did not carry the ``catalog:<n>`` shape made the
release-gate assertions raise ``IndexError`` (recorded as an opaque per-case error), and the display
ordering in ``applied_response`` crashed the same way. The ids are now validated on input and parsed
defensively.
"""
import types

import pytest
from fastapi import HTTPException

from app.schemas.ai_skill import SkillEvidence, SkillInputEnvelope, SkillScope
from app.services.ai_skills import field_rerank, runtime
from app.services.ai_skills.evaluation import mandatory_assertions

SCOPE = {"scope_type": "project", "institution_id": 1, "project_id": 1}


def _envelope(fact_ids, *, kind="catalog_field", task_key=None):
    facts = [
        SkillEvidence(
            id=value,
            kind=kind,
            value={"column_name": "cert_type", "table_name": "ecif_customer"},
            source={"source_type": "catalog_column", "source_id": "1", "source_version": "1",
                    "locator": "ecif.ecif_customer.cert_type", "scope": SCOPE},
            confidentiality="internal",
        )
        for value in fact_ids
    ]
    return SkillInputEnvelope(
        skill_key="field_semantic_matching",
        task_key=task_key or runtime.FIELD_RERANK_TASK,
        scope=SkillScope(**SCOPE),
        subject_ref="field_candidates:1:0123456789abcdef",
        facts=facts,
    )


def test_is_candidate_id_accepts_only_the_contract_shape():
    assert runtime.is_candidate_id("catalog:1")
    assert runtime.is_candidate_id("catalog:42")
    for bad in ("f1", "", "catalog:", "catalog:0", "catalog:01", "catalog:1a", "target_field:1", "Catalog:1"):
        assert not runtime.is_candidate_id(bad), bad


def test_bad_catalog_field_id_fails_with_a_contract_error():
    with pytest.raises(HTTPException) as excinfo:
        runtime.require_field_candidate_ids(_envelope(["f1"]))
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == {"error_code": "field_candidate_id_invalid"}


def test_non_candidate_fact_kinds_are_ignored():
    # An asset_identity fact is not part of the rerank whitelist, so it never fails the shape check.
    assert runtime.require_field_candidate_ids(_envelope(["fact_1"], kind="asset_identity")) == []
    assert runtime.require_field_candidate_ids(_envelope([])) == []


def test_invocation_requires_at_least_one_candidate():
    # Without a candidate the field_ranking_v1 contract can never be satisfied: unusable input.
    with pytest.raises(HTTPException) as excinfo:
        runtime.require_field_candidate_ids(_envelope(["fact_1"], kind="asset_identity"), require_present=True)
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == {"error_code": "field_candidates_required"}
    assert runtime.require_field_candidate_ids(_envelope(["catalog:2"]), require_present=True) == ["catalog:2"]

def test_mandatory_assertions_keeps_probing_with_a_valid_whitelist():
    assertions = mandatory_assertions(_envelope(["catalog:3"]))
    assert assertions["unknown_reference_rejected"] is True
    assert assertions["native_unknown_evidence_rejected"] is True
    assert assertions["native_unknown_reference_rejected"] is True


def test_mandatory_assertions_reports_a_contract_error_instead_of_indexerror():
    with pytest.raises(HTTPException) as excinfo:
        mandatory_assertions(_envelope(["f1"]))
    assert excinfo.value.detail == {"error_code": "field_candidate_id_invalid"}


def test_applied_response_orders_odd_ids_without_crashing():
    ranking = types.SimpleNamespace(ranking=[
        types.SimpleNamespace(candidate_id="f1", score=0.4, rationale="low", evidence_refs=[]),
        types.SimpleNamespace(candidate_id="catalog:2", score=0.9, rationale="high", evidence_refs=[]),
    ])
    recall = {
        "context_hash": "a" * 64,
        "candidates": [
            {"candidate_id": "f1", "score": 0.4, "rationale": "low"},
            {"candidate_id": "catalog:2", "score": 0.9, "rationale": "high"},
        ],
        "scanned_count": 2, "returned_count": 2,
    }
    response = field_rerank.applied_response(recall, ranking, provenance={}, model_metadata={"run_id": 7})
    assert [item["candidate_id"] for item in response["candidates"]] == ["catalog:2", "f1"]
    assert response["ranking_mode"] == "model_rerank"
    assert response["candidates"][0]["rank_source"] == "model"


def test_candidate_ordinal_keeps_numeric_tie_break():
    assert field_rerank.candidate_ordinal("catalog:7") == 7
    assert field_rerank.candidate_ordinal("f1") == field_rerank.UNRANKED_ORDINAL
    ordered = sorted(["catalog:10", "catalog:2", "f1"], key=field_rerank.candidate_ordinal)
    assert ordered == ["catalog:2", "catalog:10", "f1"]
