"""P2-B: the rerank path narrows its candidate list to the model context budget.

Recall answers ``top_k`` (20 by default) candidates, while the shipped profile fits only a handful
of them in one prompt.  Before this change that mismatch surfaced as a plain 409 on an ordinary
request.  Two things are now true instead:  the candidate descriptor carries only differentiated
content (no absent keys, no duplicated version digest), and the weakest tail is dropped *before*
the model call, with the reduction reported back next to the untouched recall count.

Reducing candidates is a visible product change, so every case here asserts what the caller can
see: how many were recalled, how many were admitted, and that no silent reordering happened.
Nothing here measures a real model; the transport is the shipped Mock.
"""
import json

import pytest
from sqlalchemy import select

from app.models import (AISkillDefinition, AISkillScopeBinding, AISkillVersion, CatalogColumn,
                        CatalogTable, Project)
from app.schemas.ai_skill import SkillScope
from app.services.ai_skills import field_rerank
from test_ai_skill_control import control_env  # noqa: F401  (pytest fixture)
from test_ai_skill_field_candidates import seeded
from test_ai_skill_field_rerank import bind_rerank_skill, recall, submit_rerank

TOP_K = 20


def _resolved(db):
    definition = db.scalar(select(AISkillDefinition).where(
        AISkillDefinition.skill_key == "field_semantic_matching"))
    binding = db.scalar(select(AISkillScopeBinding).where(
        AISkillScopeBinding.definition_id == definition.id))
    return definition, db.get(AISkillVersion, binding.version_id)


def _envelope(db, query, baseline):
    project = db.get(Project, query["project_id"])
    scope = SkillScope(scope_type="project", institution_id=project.institution_id, project_id=project.id)
    envelope, blocked = field_rerank.build_rerank_envelope(project, scope, query["target_field_id"], baseline)
    assert blocked is None
    return envelope


@pytest.fixture
def wide_env(control_env):
    """A project whose recall snapshot (20 real candidates) is wider than the context budget.

    The shipped seed carries only two matching columns, so eighteen further columns are added to
    reach the default ``top_k``.  They are real rows in the same catalog, not fabricated facts.
    """

    query, _ = seeded(control_env)
    client, factory, _, scope, _ = control_env
    bind_rerank_skill(control_env)
    with factory() as db:
        table = db.scalar(select(CatalogTable).where(CatalogTable.project_id == scope["project_id"]))
        for index in range(TOP_K - 2):
            db.add(CatalogColumn(project_id=scope["project_id"], datasource_id=table.datasource_id,
                                 catalog_table_id=table.id, schema_name=table.schema_name,
                                 table_name=table.table_name, column_name=f"unmatched_{index}",
                                 column_comment=f"补充列 {index}", enabled=True))
        db.commit()
    baseline = recall(client, query)
    assert baseline["returned_count"] == TOP_K
    with factory() as db:
        built = _envelope(db, query, baseline)
        fitted, dropped = field_rerank.fit_rerank_envelope(db, *_resolved(db), built)
    return {"query": query, "baseline": baseline, "built": built, "fitted": fitted,
            "dropped": dropped, "client": client, "factory": factory}


def test_the_descriptor_carries_no_absent_or_duplicated_field(wide_env):
    """Only differentiated content travels: an absent key costs budget and tells the model nothing."""

    for fact in wide_env["built"].facts:
        assert None not in fact.value.values()
        assert "" not in fact.value.values()
        # The digest already travels on ``source.source_version``; sending it inside ``value``
        # charged the context budget twice for one identifier.
        assert "source_version" not in fact.value
        assert fact.source.source_version


def test_the_differentiated_descriptor_shrinks_each_candidate(wide_env):
    """The trim is measurable on the wire, not just in a field list: bytes per candidate drop."""

    per_candidate = len(json.dumps([item.model_dump(mode="json") for item in wide_env["built"].facts],
                                   ensure_ascii=False).encode("utf-8")) / TOP_K
    # Before the trim each candidate cost ~786 bytes; the empty keys and the duplicate digest are
    # the only things removed, so the drop is bounded and must not be zero.
    assert 600 <= per_candidate <= 700, per_candidate


def test_the_default_recall_snapshot_is_narrowed_instead_of_refused(wide_env):
    """An ordinary ``top_k=20`` request must reach the model instead of failing on the budget."""

    admitted = len(wide_env["fitted"].facts)
    assert admitted < TOP_K

    response = submit_rerank(wide_env["client"], wide_env["query"], wide_env["baseline"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "model_rerank"
    # Recall stays honest: the recall count is not rewritten to the admitted count.
    assert body["returned_count"] == TOP_K
    assert len(body["candidates"]) == admitted
    assert body["rerank"]["candidate_scope"] == {
        "recalled": TOP_K, "admitted": admitted,
        "dropped_for_context_budget": TOP_K - admitted, "reason": "model_context_budget"}


def test_the_admitted_set_keeps_the_recall_order_of_the_strongest_candidates(wide_env):
    """Dropping from the tail neither reorders nor promotes: admitted is a strict prefix of recall."""

    recalled_ids = [item.id for item in wide_env["built"].facts]
    assert recalled_ids == [item["candidate_id"] for item in wide_env["baseline"]["candidates"]]
    admitted_ids = [item.id for item in wide_env["fitted"].facts]
    assert admitted_ids == recalled_ids[:len(admitted_ids)]


def test_a_snapshot_that_already_fits_reports_no_reduction(wide_env):
    """The reduction record stays absent when nothing was dropped, rather than a misleading zero."""

    narrowed = {**wide_env["query"], "top_k": 1}
    small = recall(wide_env["client"], narrowed)
    assert small["returned_count"] == 1

    response = submit_rerank(wide_env["client"], narrowed, small)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rerank"]["candidate_scope"] is None
    assert len(body["candidates"]) == 1


def test_a_budget_that_cannot_hold_one_candidate_still_fails_loudly(control_env, monkeypatch):
    """Narrowing must never become an empty ranking: zero admitted candidates is still a refusal."""

    query, _ = seeded(control_env)
    client, _, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    monkeypatch.setattr(field_rerank, "RERANK_MAX_INPUT_BYTES", 64)

    response = submit_rerank(client, query, baseline)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "context_budget_exceeded"
    assert field_rerank.MIN_RERANK_CANDIDATES == 1
