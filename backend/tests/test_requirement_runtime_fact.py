"""P2-A 脱敏运行事实包：验证强度只降不升的隔离测试。"""

from __future__ import annotations

import copy

import pytest

from app.services.requirement_runtime_fact import (
    FACT_PACK_VERSION,
    LEVEL_FULL,
    LEVEL_SAMPLED,
    LEVEL_STATIC,
    STATUS_PARTIAL,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    claim_allowed,
    fact_pack_gaps,
    pack_sha256,
    validate_fact_pack,
)

FULL_PACK = {
    "pack_version": FACT_PACK_VERSION,
    "source": {
        "kind": "bank_authorized_export",
        "exported_by": "data-ops",
        "exported_at": "2026-10-20T09:00:00+08:00",
        "file_sha256": "a" * 64,
    },
    "script": {"version_id": 12, "batch_id": "batch-20261020", "script_hash": "b" * 64},
    "run": {
        "execution_batch": "run-20261020-01",
        "business_date": "2026-10-19",
        "parameters": {"loan_type": "normal"},
        "metadata_version": "metadata-2026-10-01",
    },
    "quality": {
        "key_uniqueness": [{"keys": ["CUST_NO", "BRANCH_NO"], "unique_rate": 1.0}],
        "null_rates": {"CUST_NO": 0.0, "LOAN_BALANCE": 0.02},
        "join_counts": [
            {"name": "loan_to_customer", "left_rows": 1000, "right_rows": 1200, "matched_rows": 998}
        ],
        "sampled_rows": 1000,
    },
}


def test_complete_pack_is_full_run_verified():
    validation = validate_fact_pack(FULL_PACK)
    assert validation.level == LEVEL_FULL
    assert validation.status == STATUS_VERIFIED
    assert validation.verified is True
    assert validation.missing == ()
    assert validation.limitations == ()
    assert validation.execution_batch == "run-20261020-01"
    assert validation.business_date == "2026-10-19"
    assert len(validation.pack_sha256) == 64
    assert claim_allowed(validation, "key_uniqueness") == LEVEL_FULL
    assert fact_pack_gaps(validation) == []


@pytest.mark.parametrize("path", [
    ("source", "file_sha256"),
    ("run", "execution_batch"),
    ("run", "business_date"),
    ("quality", "key_uniqueness"),
    ("quality", "join_counts"),
])
def test_missing_any_required_fact_blocks_full_run_claim(path):
    pack = copy.deepcopy(FULL_PACK)
    section = pack[path[0]]
    section.pop(path[1])
    validation = validate_fact_pack(pack)
    assert validation.level != LEVEL_FULL
    assert validation.status != STATUS_VERIFIED
    assert ".".join(path) in validation.missing
    assert claim_allowed(validation, "key_uniqueness") == LEVEL_STATIC
    assert any("运行事实未达到全量运行验证" in text for text in validation.limitations)
    gaps = fact_pack_gaps(validation)
    assert gaps and gaps[0]["status"] == "open"
    assert gaps[0]["pack_sha256"] == validation.pack_sha256


def test_missing_run_facts_with_source_only_downgrades_to_sampled():
    pack = {"pack_version": FACT_PACK_VERSION, "source": {"file_sha256": "c" * 64}}
    validation = validate_fact_pack(pack)
    assert validation.level == LEVEL_SAMPLED
    assert validation.status == STATUS_PARTIAL
    assert "run.execution_batch" in validation.missing
    assert claim_allowed(validation, "script_hash") == LEVEL_SAMPLED
    assert claim_allowed(validation, "key_uniqueness") == LEVEL_STATIC


def test_empty_pack_is_static_inference_only():
    validation = validate_fact_pack({})
    assert validation.level == LEVEL_STATIC
    assert validation.status == STATUS_UNVERIFIED
    assert set(validation.missing) == {
        "source.file_sha256",
        "run.execution_batch",
        "run.business_date",
        "quality.key_uniqueness",
        "quality.join_counts",
    }
    assert claim_allowed(validation, "null_rate") == LEVEL_STATIC


def test_unknown_pack_version_is_an_error_not_a_warning():
    pack = copy.deepcopy(FULL_PACK)
    pack["pack_version"] = "runtime-fact-v0"
    validation = validate_fact_pack(pack)
    assert validation.level == LEVEL_STATIC
    assert validation.status == STATUS_UNVERIFIED
    assert any(issue.code == "pack_version_unknown" for issue in validation.issues)
    assert any("pack_version_unknown" in text for text in validation.limitations)


def test_invalid_numbers_are_rejected():
    pack = copy.deepcopy(FULL_PACK)
    pack["quality"]["key_uniqueness"][0]["unique_rate"] = 1.4
    pack["quality"]["null_rates"]["CUST_NO"] = -0.1
    pack["quality"]["join_counts"][0]["matched_rows"] = 5000
    validation = validate_fact_pack(pack)
    codes = {issue.code for issue in validation.issues}
    assert "key_uniqueness_rate_invalid" in codes
    assert "null_rate_invalid" in codes
    assert "join_counts_matched_exceeds_left" in codes
    assert validation.status == STATUS_UNVERIFIED


def test_invalid_business_date_is_rejected():
    pack = copy.deepcopy(FULL_PACK)
    pack["run"]["business_date"] = "2026-02-30"
    validation = validate_fact_pack(pack)
    assert any(issue.code == "business_date_invalid" for issue in validation.issues)
    assert "run.business_date" in validation.missing
    assert validation.level != LEVEL_FULL


def test_pack_hash_is_stable_and_key_order_independent():
    first = pack_sha256(FULL_PACK)
    shuffled = dict(reversed(list(copy.deepcopy(FULL_PACK).items())))
    assert pack_sha256(shuffled) == first
    changed = copy.deepcopy(FULL_PACK)
    changed["run"]["business_date"] = "2026-10-20"
    assert pack_sha256(changed) != first


def test_unknown_fact_is_never_promoted():
    validation = validate_fact_pack(FULL_PACK)
    assert claim_allowed(validation, "invented_metric") == LEVEL_STATIC
