import asyncio

import pytest
from pydantic import BaseModel

from app.models import ModelCallLog, Project
from app.services.llm.base import LLMProviderError, ModelCallMetadata
from app.services.llm.execution_metadata import build_execution_metadata, deterministic_execution_metadata
from app.services.llm.prompt_runtime import PromptRuntime, execute_runtime_chat_with_metadata


class DemoOutput(BaseModel):
    answer: str


class CitedOutput(BaseModel):
    answer: str
    citations: list[dict] = []
    unsupported_claims: list[str] = []


def _runtime(provider: str = "mock") -> PromptRuntime:
    return PromptRuntime(
        prompt_key="lineage_edge_explanation",
        version=7,
        system_prompt="test",
        user_template="target: {target}\nevidence: {evidence}",
        model_profile_id=None,
        provider_type=provider,
        base_url=None,
        model_name="demo-model",
        api_key_env_name=None,
        local_only=provider == "mock",
        config={},
    )


class _DemoService:
    def __init__(self, provider: str, *, fail: bool = False) -> None:
        self.provider = provider
        self.model = "demo-model"
        self.last_call = ModelCallMetadata(provider=provider, model="demo-model", latency_ms=3)
        self.fail = fail

    async def chat_structured(self, system_prompt, user_prompt, response_schema):
        if self.fail:
            raise LLMProviderError("provider unavailable", error_type="provider_error")
        return response_schema(answer="ok")


def test_execution_metadata_distinguishes_mock_real_and_deterministic() -> None:
    mock = build_execution_metadata(_runtime("mock"))
    real = build_execution_metadata(_runtime("openai_compatible"))
    rule = deterministic_execution_metadata("lineage_facts")

    assert mock["execution_kind"] == "mock_model"
    assert mock["provider"] == "mock"
    assert real["execution_kind"] == "real_model"
    assert real["provider"] == "cloud"
    assert rule["execution_kind"] == "deterministic"
    assert rule["provider"] == "none"


@pytest.mark.parametrize("provider", ["mock", "openai_compatible"])
def test_successful_runtime_persists_execution_metadata(db_session, monkeypatch, provider) -> None:
    import app.services.llm.prompt_runtime as prompt_runtime

    project = Project(name=f"metadata-{provider}")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    service = _DemoService(provider)
    monkeypatch.setattr(prompt_runtime, "get_runtime_llm_service", lambda *args, **kwargs: service)
    runtime = _runtime(provider)
    budget = {"unit": "bytes", "limit": 100, "used": 4, "complete": True}

    output, metadata = asyncio.run(execute_runtime_chat_with_metadata(
        db_session,
        project.id,
        runtime,
        "demo",
        DemoOutput,
        context_budget=budget,
    ))

    assert output == {"answer": "ok"}
    assert metadata["execution_kind"] == ("mock_model" if provider == "mock" else "real_model")
    assert metadata["context_complete"] is True
    db_session.commit()
    log = db_session.query(ModelCallLog).filter_by(project_id=project.id).one()
    assert log.execution_kind == metadata["execution_kind"]
    assert log.context_hash == metadata["context_hash"]
    assert log.context_budget_json == budget
    assert log.execution_metadata_json["skill_key"] == "lineage_edge_explanation"
    assert log.execution_metadata_json["skill_version"] == "v7"
    assert log.output_hash == metadata["output_hash"]


def test_model_failure_persists_degraded_metadata_and_raises(db_session, monkeypatch) -> None:
    import app.services.llm.prompt_runtime as prompt_runtime

    project = Project(name="metadata-degraded")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    service = _DemoService("openai_compatible", fail=True)
    monkeypatch.setattr(prompt_runtime, "get_runtime_llm_service", lambda *args, **kwargs: service)

    with pytest.raises(LLMProviderError) as raised:
        asyncio.run(execute_runtime_chat_with_metadata(
            db_session,
            project.id,
            _runtime("openai_compatible"),
            "demo",
            DemoOutput,
        ))

    metadata = raised.value.execution_metadata
    assert metadata["execution_kind"] == "degraded"
    assert metadata["degraded_reason"] == "provider_error"
    log = db_session.query(ModelCallLog).filter_by(project_id=project.id, status="failed").one()
    assert log.execution_kind == "degraded"
    assert log.execution_metadata_json["degraded_reason"] == "provider_error"


def test_citations_outside_governed_input_are_rejected_and_persisted(
    db_session,
    monkeypatch,
) -> None:
    import app.services.llm.prompt_runtime as prompt_runtime

    project = Project(name="metadata-citations")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    valid = {
        "source_type": "metadata",
        "source_id": 7,
        "fact_type": "target_field",
    }
    invalid = {
        "citation_id": "metadata:999:target_field",
    }

    class CitationService(_DemoService):
        async def chat_structured(self, system_prompt, user_prompt, response_schema):
            return response_schema(
                answer="ok",
                citations=[valid, invalid],
                unsupported_claims=["无法证明的历史口径"],
            )

    monkeypatch.setattr(
        prompt_runtime,
        "get_runtime_llm_service",
        lambda *args, **kwargs: CitationService("mock"),
    )

    output, metadata = asyncio.run(execute_runtime_chat_with_metadata(
        db_session,
        project.id,
        _runtime("mock"),
        "demo",
        CitedOutput,
        allowed_citation_refs={"metadata:7:target_field"},
    ))

    assert output["citations"] == [valid]
    assert output["citation_validation"] == {
        "accepted_count": 1,
        "rejected_count": 1,
    }
    assert metadata["citations"] == [valid]
    assert metadata["rejected_claims"] == [
        "无法证明的历史口径",
        {
            "citation": invalid,
            "reason": "out_of_scope",
            "reference": "metadata:999:target_field",
        },
    ]
    db_session.commit()
    log = db_session.query(ModelCallLog).filter_by(project_id=project.id).one()
    assert log.citations_json == [valid]
    assert log.rejected_claims_json == metadata["rejected_claims"]
