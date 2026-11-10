"""Judge 关闭时的确定性支撑门槛（RAG 续作 S3）。

合法引用编号只证明"引用可解析"，不证明"内容支撑断言"。judge 关闭时，若断言
里出现被引用原文没有的字段码，结论不能显示为已获支持的 grounded。
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.services.rag import grounded_answer_service as grounded


def _citation(unit_id, quoted):
    return {
        "citation_id": f"knowledge-unit-{unit_id}",
        "knowledge_unit_id": unit_id,
        "label": f"知识单元 {unit_id}",
        "quoted_content": quoted,
    }


def _run(db_session, monkeypatch, *, answer, quoted, citations=None):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "off", raising=False)
    item = dict(
        knowledge_unit_id=1,
        content=quoted,
        confidentiality_level="internal",
        rerank_score=1,
    )
    monkeypatch.setattr(grounded.HybridRetriever, "search", lambda *a, **k: (SimpleNamespace(id=1), [item]))
    monkeypatch.setattr(grounded, "document_citation", lambda *a: (citations or [_citation(1, quoted)])[0])
    monkeypatch.setattr(grounded, "validate_citations", lambda *a, **k: None)
    monkeypatch.setattr(grounded, "get_prompt_runtime", lambda *a: None)
    monkeypatch.setattr(grounded, "evidence_runtime", lambda runtime: runtime)
    monkeypatch.setattr(grounded, "prepare_model_input", lambda *a, **k: "synthetic evidence")

    async def _answer(*_args, **_kwargs):
        return {"answer": answer, "confidence_level": "high", "supported_claims": []}, {}

    monkeypatch.setattr(grounded, "execute_runtime_chat_with_metadata", _answer)
    return asyncio.run(grounded.grounded_answer(db_session, 1, "question"))


def test_supported_field_code_keeps_grounded(db_session, monkeypatch):
    """断言里的字段码确实出现在被引用原文：维持 grounded。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，合作方式按 F250007 填报。",
        quoted="数据项编码：F250007；数据项名称：合作方式。",
    )
    assert result["answer_status"] == "grounded"
    assert result["unsupported_claims"] == []


def test_field_code_missing_from_cited_text_downgrades_to_needs_confirmation(db_session, monkeypatch):
    """合法编号 + 断言里的字段码不在被引用原文：不能算 grounded。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，发卡合作机构代码按 F090006 填报。",
        quoted="数据项编码：F250007；数据项名称：合作方式。",
    )
    assert result["answer_status"] == "needs_confirmation"
    assert any("F090006" in claim for claim in result["unsupported_claims"])
    assert any("核对引用原文" in question for question in result["open_questions"])


def test_answer_without_field_codes_is_not_penalised(db_session, monkeypatch):
    """断言不含字段码时，确定性检查不误伤。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，合作方式应在协议签订后按实际填报。",
        quoted="数据项编码：F250007；数据项名称：合作方式。",
    )
    assert result["answer_status"] == "grounded"


def test_citation_without_bracketed_id_is_not_grounded(db_session, monkeypatch):
    """模型没有用 [N] 引用时所答内容没有可核对依据：进入待确认而不是 grounded。"""

    result = _run(
        db_session, monkeypatch,
        answer="合作方式按 F090006 填报。",
        quoted="数据项编码：F250007；数据项名称：合作方式。",
    )
    assert result["answer_status"] == "needs_confirmation"
