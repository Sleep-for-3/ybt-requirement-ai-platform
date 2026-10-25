"""P1-C 生成用量与费用对账（纯函数 + API）。

这些测试只主张可核对的数字：provider 回报的 token、显式价格表算出的费用、
以及"缺数据就标 unknown"的行为。它们不主张任何业务准确率。
"""

from decimal import Decimal

import pytest

from app.services.requirement_generation_cost import (
    ESTIMATE_METHOD,
    LEDGER_VERSION,
    attempt_record,
    cost_for,
    estimate_tokens,
    estimated_usage,
    normalize_usage,
    price_for,
    summarize_ledger,
)
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401 (pytest fixtures)

PRICES = {
    "model-a": {"input_per_million": 2, "output_per_million": 8, "currency": "CNY"},
}


def provider_attempt(*, attempt=1, input_tokens=1000, output_tokens=500, model="model-a", latency_ms=120, retry_count=0, failed=False):
    return attempt_record(
        attempt=attempt,
        execution_metadata={
            "execution_kind": "real_model",
            "provider": "cloud",
            "provider_type": "openai_compatible",
            "model_name": model,
            "prompt_key": "requirement_field_candidate",
            "prompt_version": 3,
            "latency_ms": latency_ms,
            "retry_count": retry_count,
            "token_usage": {
                "usage_available": True,
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "source": "provider_reported",
            },
        },
        failed=failed,
    )


def item(field_id, usage, status="completed"):
    return {"field_id": field_id, "section": "business", "status": status, "usage": usage}


def test_normalize_usage_keeps_provider_numbers_and_marks_source():
    normalized = normalize_usage({"usage_available": True, "prompt_tokens": 10, "completion_tokens": 4})
    assert normalized["source"] == "provider_reported"
    assert normalized["available"] is True
    assert (normalized["input_tokens"], normalized["output_tokens"], normalized["total_tokens"]) == (10, 4, 14)


def test_missing_usage_is_unavailable_not_zero():
    normalized = normalize_usage({"usage_available": False})
    assert normalized["source"] == "unavailable"
    assert normalized["input_tokens"] is None
    assert normalized["output_tokens"] is None
    # 关键：不可用不能被当成 0 token 记账。
    assert normalized["total_tokens"] is None


def test_estimates_are_labelled_and_never_masquerade_as_provider_tokens():
    estimate = estimated_usage("客户号：CUST_NO", {"business_definition": "客户号口径"})
    assert estimate["source"] == "estimated"
    assert estimate["available"] is False
    assert estimate["estimate_method"] == ESTIMATE_METHOD
    assert estimate["input_tokens"] > 0
    # 估算值不参与 provider 计费口径。
    assert cost_for(estimate, "model-a", PRICES) is None


def test_estimate_does_not_use_vector_dimension_as_token_count():
    # 512 维向量不是 512 token：估算必须随文本长度变化。
    assert estimate_tokens("") == 0
    short = estimate_tokens("正常贷款")
    long = estimate_tokens("正常贷款" * 50)
    assert long > short * 10


def test_cost_requires_both_provider_usage_and_explicit_price():
    usage = {"usage_available": True, "prompt_tokens": 1_000_000, "completion_tokens": 0}
    cost = cost_for(usage, "model-a", PRICES)
    assert cost["amount"] == Decimal("2.000000")
    assert cost["pricing_version"]
    # 没有价格就是 None，不能当 0。
    assert cost_for(usage, "unknown-model", PRICES) is None
    assert cost_for(usage, "model-a", None) is None
    assert price_for("model-a", None) is None


def test_attempt_record_keeps_provider_model_prompt_and_retry_versions():
    record = provider_attempt(retry_count=1, latency_ms=321)
    assert record["provider"] == "openai_compatible"
    assert record["model"] == "model-a"
    assert record["prompt_version"] == 3
    assert record["latency_ms"] == 321
    assert record["retry_count"] == 1
    assert record["failed"] is False


@pytest.mark.parametrize("count", [1, 10, 30])
def test_ledger_reconciles_one_ten_thirty_targets(count):
    items = [item(field_id=i, usage={"attempts": [provider_attempt()]}) for i in range(1, count + 1)]
    ledger = summarize_ledger(items, prices=PRICES, budget="0.001")
    assert ledger["ledger_version"] == LEDGER_VERSION
    assert ledger["item_count"] == count
    assert ledger["attempt_count"] == count
    assert ledger["input_tokens"] == 1000 * count
    assert ledger["output_tokens"] == 500 * count
    assert ledger["usage_sources"] == {"provider_reported": count, "estimated": 0, "unavailable": 0}
    # 每项 1000 input * 2/M + 500 output * 8/M = 0.002 + 0.004 = 0.006
    assert Decimal(ledger["cost"]["amount"]) == Decimal("0.006000") * count
    assert ledger["budget"]["status"] == "exceeded"


def test_ledger_is_idempotent_and_never_double_counts_on_replay():
    items = [item(1, {"attempts": [provider_attempt(), provider_attempt(attempt=2)]})]
    first = summarize_ledger(items, prices=PRICES, budget="100")
    second = summarize_ledger(items, prices=PRICES, budget="100")
    assert first == second
    assert first["attempt_count"] == 2
    assert first["input_tokens"] == 2000


def test_ledger_marks_unknown_when_any_item_cannot_be_priced():
    items = [
        item(1, {"attempts": [provider_attempt()]}),
        item(2, {"attempts": [provider_attempt(model="unpriced-model")]}),
    ]
    ledger = summarize_ledger(items, prices=PRICES, budget="100")
    assert ledger["cost"] is None
    assert ledger["partial_cost_amount"] is not None
    assert ledger["budget"]["status"] == "unknown"
    assert ledger["usage_sources"]["provider_reported"] == 2


def test_ledger_marks_unknown_without_budget_configuration():
    items = [item(1, {"attempts": [provider_attempt()]})]
    ledger = summarize_ledger(items, prices=PRICES, budget=None)
    assert ledger["budget"]["status"] == "unknown"
    assert ledger["cost"] is not None  # 费用算得出，但预算无法判定


def test_ledger_counts_failed_attempts_and_items_without_calls():
    usage = {"attempts": [provider_attempt(failed=True), provider_attempt(attempt=2)]}
    ledger = summarize_ledger([item(1, usage), item(2, {"attempts": []}, status="completed")], prices=PRICES, budget="100")
    assert ledger["failed_attempt_count"] == 1
    assert ledger["attempt_count"] == 2
    # 没有模型调用的 item（例如确定性 Skill 输出）如实记为 unavailable。
    assert ledger["usage_sources"]["unavailable"] == 1


def test_api_generation_usage_endpoint_reports_honest_status(snapshot_api, monkeypatch):
    from app.models import RequirementGenerationInput, RequirementGenerationItem

    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    created = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id], "sections": ["business"],
        "idempotency_key": "usage-ledger-one"})
    assert created.status_code == 201, created.text
    input_id = created.json()["id"]
    row = db.get(RequirementGenerationInput, input_id)
    row_item = RequirementGenerationItem(input_id=input_id, field_id=field.id, section="business",
                                        status="completed",
                                        usage_json={"schema_version": LEDGER_VERSION,
                                                    "final_status": "completed",
                                                    "self_correction_attempts": 1,
                                                    "attempts": [provider_attempt()]})
    db.add(row_item)
    db.commit()

    response = client.get(base + f"/generation-inputs/{input_id}/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attempt_count"] == 1
    assert body["input_tokens"] == 1000
    assert body["stale"] is False
    # 未配置价格 → 费用与预算都必须 unknown，不能显示 0。
    assert body["cost"] is None
    assert body["budget"]["status"] == "unknown"

    # 配置显式价格与预算后，同一份明细必须能算出确定金额并判超预算。
    monkeypatch.setattr("app.api.requirements._generation_pricing",
                        lambda db: (PRICES, "0.001"))
    priced = client.get(base + f"/generation-inputs/{input_id}/usage").json()
    assert Decimal(priced["cost"]["amount"]) == Decimal("0.006000")
    assert priced["budget"]["status"] == "exceeded"

    missing = client.get(base + "/generation-inputs/999999/usage")
    assert missing.status_code == 404
