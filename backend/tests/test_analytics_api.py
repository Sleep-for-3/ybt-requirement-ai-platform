from datetime import UTC, datetime

from app.services.analytics.metric_query_service import _metric_payload


def test_zero_denominator_is_explicitly_unavailable() -> None:
    payload = _metric_payload("evidence_coverage", 0, 0, datetime.now(UTC))
    assert payload["value"] is None
    assert payload["numerator"] == 0
    assert payload["denominator"] == 0


def test_metric_payload_contains_provenance_and_scope() -> None:
    now = datetime.now(UTC)
    payload = _metric_payload("business_definition_coverage", 4, 5, now)
    assert payload["value"] == 0.8
    assert payload["as_of"] == now.isoformat()
    assert payload["definition"]["numerator_definition"]
    assert payload["definition"]["dimensions"]
