from app.services.analytics.metric_registry import METRIC_REGISTRY, get_metric_definition


def test_registry_has_core_governed_metrics_with_dimensions() -> None:
    expected = {
        "readiness_score",
        "business_definition_coverage",
        "technical_lineage_coverage",
        "evidence_coverage",
        "review_completion_rate",
        "review_sla_compliance",
        "high_risk_impact_count",
        "schema_drift_count",
    }
    assert expected <= set(METRIC_REGISTRY)
    assert all(definition.dimensions for definition in METRIC_REGISTRY.values())
    assert all(definition.certification_status == "confirmed" for definition in METRIC_REGISTRY.values())


def test_metric_definition_is_single_source_of_truth() -> None:
    definition = get_metric_definition("evidence_coverage")
    assert definition.metric_name == "证据完备率"
    assert "至少拥有一条 Evidence" in definition.numerator_definition
    assert "Mapping" in definition.denominator_definition


def test_unknown_metric_fails_closed() -> None:
    try:
        get_metric_definition("not-a-real-metric")
    except KeyError as error:
        assert "Unknown governed metric" in str(error)
    else:
        raise AssertionError("unknown metric must fail closed")

