"""W08: one outbound gateway decides for both the rerank and the prompt paths.

The two paths used to decide independently, so the same project/material could be denied by one
and allowed by the other. These tests pin the converged behaviour and - importantly - that the
gateway is no more permissive than either path was: the allow list stays empty by default, unknown
classifications stay restricted, and catalog structure keeps its confidential floor.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai_skills import field_rerank
from app.services.security.content_redactor import ensure_external_allowed
from app.services.security.outbound_policy import (
    CATALOG_FLOOR,
    LEVELS,
    UNKNOWN_LEVEL,
    catalog_confidentiality_floor,
    ensure_external_send_allowed,
    external_send_denied,
    normalize_level,
    outbound_authorized_project_ids,
)


def _project(project_id: int = 11, level: str | None = "internal"):
    return SimpleNamespace(id=project_id, confidentiality_level=level)


def test_both_paths_share_one_decision():
    """The rerank wrapper and the prompt helper must agree for the same material."""

    project = _project()
    floor = field_rerank.confidentiality_floor(project)
    # the rerank path denies the cloud send ...
    assert external_send_denied(floor, False) is not None
    # ... and the prompt path reaches the same verdict through the same gateway
    with pytest.raises(ValueError):
        ensure_external_allowed(floor, False)
    assert catalog_confidentiality_floor(project) == floor


def test_the_gateway_is_the_single_source_for_both_names():
    """Patching the gateway is observed through the rerank wrapper too."""

    from app.services.security import outbound_policy

    project = _project()
    assert field_rerank.confidentiality_floor(project) == "confidential"
    with pytest.MonkeyPatch.context() as patch:
        # the wrapper imports the symbol at call time, so a patched gateway is observed
        patch.setattr(outbound_policy, "catalog_confidentiality_floor", lambda *a, **k: "public")
        assert field_rerank.confidentiality_floor(project) == "public"
        assert external_send_denied("public", False) is None


def test_the_default_configuration_does_not_authorize_any_project():
    # explicit values are parsed exactly, never guessed
    assert outbound_authorized_project_ids("") == set()
    assert outbound_authorized_project_ids(" , , ") == set()
    assert outbound_authorized_project_ids("11, 12") == {"11", "12"}
    # non-numeric entries are ignored rather than treated as authorization
    assert outbound_authorized_project_ids("abc, 12, ,") == {"12"}
    # reading the live setting must agree with parsing it the same way
    from app.core.settings import get_settings
    raw = get_settings().ai_external_model_allowed_project_ids
    assert outbound_authorized_project_ids() == outbound_authorized_project_ids(raw)


def test_an_unauthorized_project_keeps_the_catalog_floor():
    for declared in ("public", "internal", "confidential", "restricted", None, "unknown"):
        floor = catalog_confidentiality_floor(_project(level=declared), authorized_ids=set())
        assert LEVELS[floor] >= LEVELS[CATALOG_FLOOR], declared


def test_an_explicitly_authorized_project_keeps_its_declared_level():
    assert catalog_confidentiality_floor(_project(11, "internal"), authorized_ids={"11"}) == "internal"
    assert catalog_confidentiality_floor(_project(11, "restricted"), authorized_ids={"11"}) == "restricted"
    assert catalog_confidentiality_floor(_project(11, None), authorized_ids={"11"}) == UNKNOWN_LEVEL


def test_unknown_levels_are_never_downgraded():
    assert normalize_level(None) == UNKNOWN_LEVEL
    assert normalize_level("") == UNKNOWN_LEVEL
    assert normalize_level("nonsense") == UNKNOWN_LEVEL
    assert normalize_level("public") == "public"
    assert external_send_denied("nonsense", False) is not None


def test_send_decision_matches_the_historical_semantics():
    # local-only providers always carry the material
    for level in ("public", "internal", "confidential", "restricted"):
        assert external_send_denied(level, True) is None
        ensure_external_send_allowed(level, True)
    # a non-local provider may carry only levels below confidential
    assert external_send_denied("public", False) is None
    assert external_send_denied("internal", False) is None
    assert external_send_denied("confidential", False) is not None
    assert external_send_denied("restricted", False) is not None
    with pytest.raises(ValueError):
        ensure_external_send_allowed("restricted", False)
    with pytest.raises(ValueError):
        ensure_external_send_allowed("confidential", False)
