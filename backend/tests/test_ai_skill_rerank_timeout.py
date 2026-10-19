"""P2-B: the field-rerank wall-clock budget is opt-in and every expiry is auditable.

The budget exists so a slow provider can degrade to the deterministic recall order instead of
holding the interactive request open.  Whether that trade is acceptable as the *default* is a
product decision, so the shipped default is ``0`` (unbounded, today's behaviour) and every case
here has to opt in explicitly.

Nothing here measures a real model: there is no external provider in this environment, so the
latency numbers below are synthetic stalls.  "Real model latency not re-measured" applies.
"""
import asyncio
import json

import pytest
from sqlalchemy import select

from fastapi import HTTPException

from app.models import AISkillDefinition, AISkillScopeBinding, AISkillVersion, ModelCallLog, Project
from app.schemas.ai_skill import SkillScope
from app.services.ai_skills.runtime import compile_input
from app.services.ai_skills import field_rerank
from app.services.llm import factory as llm_factory
from app.services.llm.mock import MockLLMService
from test_ai_skill_control import control_env
from test_ai_skill_field_candidates import seeded
from test_ai_skill_field_rerank import bind_rerank_skill, log_count, recall, submit_rerank


@pytest.fixture(autouse=True)
def _unbounded_by_default(monkeypatch):
    """Pin the shipped default explicitly: an ambient ``.env`` must not enable degradation here."""

    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "field_rerank_timeout_seconds", 0)
    monkeypatch.setattr(get_settings(), "ai_external_model_allowed_project_ids", "", raising=False)


def stalling_transport(seconds: float):
    """A Mock-shaped provider that answers only after ``seconds`` -- a synthetic stall, not a model."""

    class StallingMock(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            if system_prompt.startswith("[AI_SKILL_FIELD_RERANK_V1]"):
                await asyncio.sleep(seconds)
            return await super().chat_json(system_prompt, user_prompt)

    return StallingMock


def budget(monkeypatch, seconds):
    # Settings only accept a whole 1..180s budget, so a fast test overrides the resolved value.
    monkeypatch.setattr(field_rerank, "rerank_timeout_seconds", lambda: float(seconds))


def rerank_logs(factory):
    with factory() as db:
        return db.scalars(select(ModelCallLog).where(
            ModelCallLog.skill_key == "field_semantic_matching").order_by(ModelCallLog.id)).all()


def test_the_shipped_default_is_still_an_unbounded_wait(control_env, monkeypatch):
    """No configured budget must mean "no budget": the slow-but-successful call stays a success."""

    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    monkeypatch.setattr(llm_factory, "MockLLMService", stalling_transport(0.02))

    assert field_rerank.rerank_timeout_seconds() == 0
    response = submit_rerank(client, query, baseline)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "model_rerank"
    assert body["execution_metadata"]["execution_kind"] == "mock_model"
    log = rerank_logs(factory)[-1]
    assert log.status == "success" and log.execution_metadata_json["degraded_reason"] is None


def test_an_expired_budget_degrades_with_an_audited_failure_record(control_env, monkeypatch):
    """The slowest path is the one that most needs a trace: an expiry writes its own failed log."""

    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    budget(monkeypatch, 0.05)
    monkeypatch.setattr(llm_factory, "MockLLMService", stalling_transport(0.6))

    response = submit_rerank(client, query, baseline)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "deterministic_recall"
    assert body["execution_metadata"]["execution_kind"] == "deterministic"
    assert body["rerank"]["status"] == "failed"
    assert body["rerank"]["error_code"] == field_rerank.RERANK_TIMEOUT_CODE
    metadata = body["rerank"]["model_metadata"]
    assert metadata["degraded_reason"] == field_rerank.RERANK_TIMEOUT_CODE
    assert metadata["execution_kind"] == "degraded"
    assert metadata["rerank_attempts"] == 1
    assert metadata["rerank_timeout_seconds"] == 0.05
    assert [item["candidate_id"] for item in body["candidates"]] == [
        item["candidate_id"] for item in baseline["candidates"]]
    assert all(item["rank_source"] == "recall" for item in body["candidates"])
    # Exactly one record: the cancelled attempt cannot log itself, the degraded run logs for it.
    assert log_count(factory) == before + 1
    log = rerank_logs(factory)[-1]
    assert log.status == "failed" and log.execution_kind == "degraded"
    assert log.error_type == field_rerank.RERANK_TIMEOUT_CODE
    assert log.execution_metadata_json["degraded_reason"] == field_rerank.RERANK_TIMEOUT_CODE
    # The response carries the in-memory run_id; the plain JSON column keeps its older copy without it
    # (same as the successful path), so only the response-side anchor is asserted here.
    assert log.id == body["rerank"]["run_id"]


def test_an_expired_budget_is_not_retried(control_env, monkeypatch):
    """Retrying an expiry would double a wait the user already paid for; the attempt stays at one."""

    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    budget(monkeypatch, 0.05)
    monkeypatch.setattr(llm_factory, "MockLLMService", stalling_transport(0.6))

    body = submit_rerank(client, query, baseline).json()

    assert body["rerank"]["model_metadata"]["rerank_attempts"] == 1
    assert log_count(factory) == before + 1
    assert field_rerank.RERANK_TIMEOUT_CODE not in field_rerank.RETRYABLE_MODEL_FAILURES


def test_a_budget_long_enough_to_pass_changes_nothing(control_env, monkeypatch):
    """The budget must not perturb the happy path's ordering, attempts or execution class."""

    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    budget(monkeypatch, 5)

    body = submit_rerank(client, query, baseline).json()

    assert body["ranking_mode"] == "model_rerank"
    assert body["execution_metadata"]["execution_kind"] == "mock_model"
    assert body["rerank"]["model_metadata"]["rerank_attempts"] == 1
    assert [item["candidate_id"] for item in body["candidates"]] == list(
        reversed([item["candidate_id"] for item in baseline["candidates"]]))


def test_rerank_timeout_must_be_bounded_and_zero_means_unset():
    """A misconfigured budget is a startup error, not a silent 0-second degradation."""

    from app.core.settings import Settings

    base = dict(_env_file=None, database_url="sqlite://", environment="test")

    def error_codes(seconds):
        return [item["code"] for item in Settings(**base, field_rerank_timeout_seconds=seconds)
                .validate_configuration() if item["severity"] == "error"]

    assert error_codes(0) == []
    assert error_codes(90) == []
    for invalid in (-1, 0.5, 181):
        assert Settings(**base, field_rerank_timeout_seconds=invalid).validate_configuration()
        assert "field_rerank_timeout_invalid" in error_codes(invalid), invalid


def test_rerank_envelope_bytes_grow_linearly_with_the_candidate_count(control_env):
    """Structural measurement only: candidate count -> envelope bytes, no model is called."""

    query, ids = seeded(control_env)
    client, factory, login, scope, _ = control_env
    result = recall(client, query)
    skill_scope = SkillScope(scope_type="project", institution_id=scope["institution_id"],
                             project_id=scope["project_id"])
    with factory() as db:
        project = db.get(Project, scope["project_id"])

    def facts_bytes(count):
        widened = [dict(result["candidates"][index % len(result["candidates"])],
                        candidate_id=f"catalog:{900000 + index}") for index in range(count)]
        envelope, blocked = field_rerank.build_rerank_envelope(
            project, skill_scope, query["target_field_id"], {**result, "candidates": widened})
        assert blocked is None
        assert len(envelope.facts) == count
        return len(json.dumps([item.model_dump(mode="json") for item in envelope.facts],
                              ensure_ascii=False).encode("utf-8"))

    one, two, ten = facts_bytes(1), facts_bytes(2), facts_bytes(10)
    # Linear in the candidate count: every fact carries the same fixed shape.
    assert two - one == ten - one - (ten - two)
    # 656 bytes per candidate after the descriptor trim (previously ~786 with the redundant
    # ``source_version`` and the empty keys); the bound is wide on purpose, not a golden number.
    assert 600 <= (ten - one) / 9 <= 750, (ten - one) / 9


def test_the_model_context_budget_binds_long_before_the_50_candidate_cap(control_env):
    """The real ceiling is the model context, not RERANK_MAX_CANDIDATES or RERANK_MAX_INPUT_BYTES.
    Measured with the shipped Mock profile (8192 context tokens, UTF-8 upper bound): the compiled
    prompt accepts 7 candidates and rejects 8 with 409 context_budget_exceeded.  The declared caps
    (50 candidates / 32000 bytes) are therefore unreachable on this profile.  That is why the
    rerank path trims the candidate list before it calls the model instead of letting an ordinary
    ``top_k=20`` recall collide with the ceiling.
    """

    query, ids = seeded(control_env)
    client, factory, login, scope, _ = control_env
    bind_rerank_skill(control_env)
    result = recall(client, query)
    skill_scope = SkillScope(scope_type="project", institution_id=scope["institution_id"],
                             project_id=scope["project_id"])
    with factory() as db:
        project = db.get(Project, scope["project_id"])
        definition = db.scalar(select(AISkillDefinition).where(
            AISkillDefinition.skill_key == "field_semantic_matching"))
        binding = db.scalar(select(AISkillScopeBinding).where(
            AISkillScopeBinding.definition_id == definition.id))
        version = db.get(AISkillVersion, binding.version_id)

    def compile_for(count):
        widened = [dict(result["candidates"][index % len(result["candidates"])],
                        candidate_id=f"catalog:{900000 + index}") for index in range(count)]
        envelope, blocked = field_rerank.build_rerank_envelope(
            project, skill_scope, query["target_field_id"], {**result, "candidates": widened})
        assert blocked is None
        with factory() as db:
            return compile_input(db, definition, version, envelope)

    compiled = compile_for(7)
    assert compiled.budget["complete"] is True
    assert compiled.budget["limit"] == 5632
    with pytest.raises(HTTPException) as raised:
        compile_for(8)
    assert raised.value.status_code == 409
    assert raised.value.detail["error_code"] == "context_budget_exceeded"
    assert raised.value.detail["budget"]["used"] > raised.value.detail["budget"]["limit"]
