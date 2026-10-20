"""⑤: opt-in citation entailment checking (``settings.citation_support_check``).

These tests drive the real validator/judge code paths and replace only the model gateway
(``app.services.llm.prompt_runtime.get_runtime_llm_service``), so no network call is ever made.

Covered:
* ``off`` (the default) makes no model call and adds no key to the answer payload -- the
  pre-existing behaviour is reproduced byte-for-byte;
* ``judge`` reports supported/unsupported/unknown per citation plus the unsupported ratio;
* an unavailable gateway degrades every citation to ``unknown`` without raising;
* empty citations and an empty answer take the no-model-call boundary paths;
* ``validate_citations`` keeps its exact messages and signature.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.settings import get_settings
from app.models import (
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    Project,
)
from app.services.llm.base import LLMProviderError, ModelCallMetadata
from app.services.rag import grounded_answer_service as grounded
from app.services.rag.citation_support import normalize_verdict, parse_judge_verdicts
from app.services.rag.citation_validator import check_citation_support, validate_citations

CALL_COUNT = {"value": 0}


class _VerdictService:
    """Fixed judge reply; records how often the gateway was asked for a judgement."""

    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def chat_json(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        CALL_COUNT["value"] += 1
        return self.payload

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


class _FailingService:
    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    async def chat_json(self, system_prompt, user_prompt):
        CALL_COUNT["value"] += 1
        raise LLMProviderError("judge unavailable", error_type="timeout", detail="ReadTimeout")

    async def embed_texts(self, texts):
        raise LLMProviderError("judge unavailable", error_type="timeout")


def _install_gateway(monkeypatch, service_factory):
    """Replace the LLM gateway factory used by the judge engine (never the real network)."""

    def factory(*_args, **_kwargs):
        return service_factory()

    monkeypatch.setattr("app.services.llm.prompt_runtime.get_runtime_llm_service", factory)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "citation.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CALL_COUNT["value"] = 0
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "off", raising=False)
    monkeypatch.setattr(settings, "ragas_judge_enabled", False, raising=False)
    yield


def _citation(index, *, unit_id=None, quoted="余额以合同为准"):
    return {
        "citation_id": f"knowledge-unit-{unit_id if unit_id is not None else index}",
        "knowledge_unit_id": unit_id if unit_id is not None else index,
        "label": f"知识单元 {index}",
        "quoted_content": quoted,
    }


# --------------------------------------------------------------------------- verdict parsing


def test_verdict_spellings_are_normalised():
    assert normalize_verdict("Supported") == "supported"
    assert normalize_verdict("支持") == "supported"
    assert normalize_verdict("不支持") == "unsupported"
    assert normalize_verdict("not_supported") == "unsupported"
    assert normalize_verdict("不确定") == "unknown"
    assert normalize_verdict(1) == "unknown"
    assert normalize_verdict("meaningless") == "unknown"


def test_payload_shapes_are_parsed():
    assert parse_judge_verdicts({"verdicts": [{"citation_id": "a", "verdict": "supported"}]})[0][
        "citation_id"
    ] == "a"
    assert parse_judge_verdicts({"claims": [{"claim": "x", "verdict": "unsupported"}]})[0][
        "claim"
    ] == "x"
    assert parse_judge_verdicts([{"verdict": "unknown"}])[0]["verdict"] == "unknown"
    assert parse_judge_verdicts({"verdict": "supported"})[0]["verdict"] == "supported"
    assert parse_judge_verdicts("not json at all") == []
    assert parse_judge_verdicts(None) == []


# --------------------------------------------------------------------------- switch off


def test_off_makes_no_model_call_and_reports_disabled(db, monkeypatch):
    def explode():  # pragma: no cover - must never be reached
        raise AssertionError("the judge gateway must not be called when the switch is off")

    _install_gateway(monkeypatch, explode)
    result = asyncio.run(
        check_citation_support(db, [_citation(1)], answer="余额以合同为准。", project_id=1)
    )
    assert result["enabled"] is False
    assert result["check"] == "off"
    assert result["judged"] is False
    assert result["verdicts"] == []
    assert CALL_COUNT["value"] == 0


def test_grounded_answer_is_unchanged_when_the_switch_is_off(db, monkeypatch):
    """Regression: the answer payload must not gain a citation_support key by default."""

    def explode(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("no judge call is allowed while citation_support_check is off")

    monkeypatch.setattr("app.services.llm.prompt_runtime.get_runtime_llm_service", explode)
    item = dict(
        knowledge_unit_id=1, content="Known.table", confidentiality_level="internal",
        rerank_score=1,
    )
    monkeypatch.setattr(grounded.HybridRetriever, "search", lambda *a, **k: (SimpleNamespace(id=1), [item]))
    monkeypatch.setattr(grounded, "document_citation", lambda *a: _citation(1, unit_id=1))
    monkeypatch.setattr(grounded, "validate_citations", lambda *a, **k: None)
    monkeypatch.setattr(grounded, "get_prompt_runtime", lambda *a: None)
    monkeypatch.setattr(grounded, "evidence_runtime", lambda runtime: runtime)
    monkeypatch.setattr(grounded, "prepare_model_input", lambda *a, **k: "synthetic evidence")

    async def answer(*_args, **_kwargs):
        return {"answer": "结论", "confidence_level": "high", "supported_claims": []}, {}

    monkeypatch.setattr(grounded, "execute_runtime_chat_with_metadata", answer)
    result = asyncio.run(grounded.grounded_answer(db, 1, "question"))
    assert "citation_support" not in result
    assert result["answer_status"] == "grounded"


# --------------------------------------------------------------------------- switch on


def test_judge_reports_supported_unsupported_and_ratio(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    service = _VerdictService(
        {
            "verdicts": [
                {"citation_id": "knowledge-unit-1", "verdict": "supported", "reason": "引文支持"},
                {"citation_id": "knowledge-unit-2", "verdict": "unsupported", "reason": "引文矛盾"},
            ]
        }
    )
    _install_gateway(monkeypatch, lambda: service)
    result = asyncio.run(
        check_citation_support(
            db,
            [_citation(1), _citation(2, quoted="余额以口头约定为准")],
            answer="余额以合同为准。",
            project_id=1,
        )
    )
    assert result["enabled"] is True and result["judged"] is True
    assert [item["verdict"] for item in result["verdicts"]] == ["supported", "unsupported"]
    assert result["supported_count"] == 1 and result["unsupported_count"] == 1
    assert result["unsupported_ratio"] == 0.5
    assert result["verdict_counts"] == {"supported": 1, "unsupported": 1, "unknown": 0}
    assert service.calls and "citation_support_check" == result["prompt_key"]


def test_citations_without_a_verdict_are_marked_unknown(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    service = _VerdictService({"verdicts": [{"citation_id": "knowledge-unit-1", "verdict": "supported"}]})
    _install_gateway(monkeypatch, lambda: service)
    result = asyncio.run(
        check_citation_support(db, [_citation(1), _citation(2)], answer="结论", project_id=1)
    )
    assert result["verdicts"][1]["verdict"] == "unknown"
    assert result["verdicts"][1]["reason"] == "judge_returned_no_verdict"
    assert result["unsupported_ratio"] == 0.0
    assert result["unknown_count"] == 1


def test_unsupported_citation_downgrades_the_answer_instead_of_staying_grounded(db, monkeypatch):
    """⑤: a legal citation id is not proof of support — an unsupported verdict must downgrade.

    This replaces the pre-B-package assertion ``answer_status == "grounded"``, which recorded the
    defect: the judge verdict was merely attached to the payload and never influenced the status.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    service = _VerdictService(
        {"verdicts": [{"citation_id": "knowledge-unit-1", "verdict": "unsupported", "reason": "矛盾"}]}
    )
    _install_gateway(monkeypatch, lambda: service)
    item = dict(
        knowledge_unit_id=1, content="Known.table", confidentiality_level="internal",
        rerank_score=1,
    )
    monkeypatch.setattr(grounded.HybridRetriever, "search", lambda *a, **k: (SimpleNamespace(id=1), [item]))
    monkeypatch.setattr(grounded, "document_citation", lambda *a: _citation(1, unit_id=1))
    monkeypatch.setattr(grounded, "validate_citations", lambda *a, **k: None)
    monkeypatch.setattr(grounded, "get_prompt_runtime", lambda *a: None)
    monkeypatch.setattr(grounded, "evidence_runtime", lambda runtime: runtime)
    monkeypatch.setattr(grounded, "prepare_model_input", lambda *a, **k: "synthetic evidence")

    async def answer(*_args, **_kwargs):
        return {"answer": "结论", "confidence_level": "high", "supported_claims": []}, {}

    monkeypatch.setattr(grounded, "execute_runtime_chat_with_metadata", answer)
    result = asyncio.run(grounded.grounded_answer(db, 1, "question"))
    support = result["citation_support"]
    assert support["enabled"] is True
    assert support["verdicts"][0]["verdict"] == "unsupported"
    assert support["unsupported_ratio"] == 1.0
    # B 包新契约：引用不支持关键结论时，不得继续以 grounded / high 呈现为已证实。
    assert result["answer_status"] == "needs_confirmation"
    assert result["answer_status"] != "grounded"
    assert result["confidence_level"] == "low"
    # 依据不丢：引用仍然保留可定位。
    assert result["citations"] and result["citations"][0]["knowledge_unit_id"] == 1

# --------------------------------------------------------------------------- degradation


def test_gateway_failure_degrades_to_unknown_without_raising(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    _install_gateway(monkeypatch, _FailingService)
    result = asyncio.run(
        check_citation_support(db, [_citation(1), _citation(2)], answer="结论", project_id=1)
    )
    assert result["degraded"] is True
    assert result["degraded_reason"] == "timeout"
    assert result["judged"] is False
    assert {item["verdict"] for item in result["verdicts"]} == {"unknown"}
    assert result["unsupported_ratio"] == 0.0


def test_empty_and_unparseable_judge_replies_do_not_raise(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    _install_gateway(monkeypatch, lambda: _VerdictService({}))
    result = asyncio.run(check_citation_support(db, [_citation(1)], answer="结论", project_id=1))
    # The judge answered, but nothing was parseable: unknown, no crash, no degradation flag.
    assert result["verdicts"][0]["verdict"] == "unknown"
    assert result["judged"] is True


# --------------------------------------------------------------------------- boundaries


def test_empty_citations_skip_the_judge(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)

    def explode():  # pragma: no cover
        raise AssertionError("empty citations must not reach the gateway")

    _install_gateway(monkeypatch, explode)
    result = asyncio.run(check_citation_support(db, [], answer="结论", project_id=1))
    assert result["citation_count"] == 0
    assert result["skip_reason"] == "no_citations"
    assert result["verdicts"] == []
    assert CALL_COUNT["value"] == 0


def test_validate_citations_contract_is_unchanged(db):
    assert validate_citations(db, []) is None
    with pytest.raises(ValueError, match="缺少 knowledge_unit_id"):
        validate_citations(db, [{"label": "no id"}])
    with pytest.raises(ValueError, match="不存在或已禁用"):
        validate_citations(db, [{"knowledge_unit_id": 999999}])


def _seed_unit(db, *, scope, project_id, confidentiality="internal"):
    document = KnowledgeDocument(
        project_id=project_id, file_name="synthetic.md", file_type="md",
        source_type="upload", storage_path="synthetic", document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project_id, document_id=document.id, version_no=1,
        file_name=document.file_name, storage_path="synthetic", file_hash="f" * 64,
    )
    db.add(version)
    db.flush()
    unit = KnowledgeUnit(
        project_id=project_id, document_id=document.id, document_version_id=version.id,
        knowledge_type="manual_note", knowledge_scope=scope, unit_type="paragraph",
        content="synthetic", normalized_content="synthetic",
        source_file_name=document.file_name, confidentiality_level=confidentiality,
        enabled=True, content_hash="a" * 64,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


def test_validate_citations_visibility_rule_is_unchanged(db):
    project = Project(name="⑤ 项目")
    db.add(project)
    db.flush()
    unit = _seed_unit(db, scope="project", project_id=project.id)
    assert validate_citations(db, [{"knowledge_unit_id": unit.id}], project_id=project.id) is None
    with pytest.raises(ValueError, match="对当前项目不可见"):
        validate_citations(db, [{"knowledge_unit_id": unit.id}], project_id=project.id + 1000)
