"""P0 确定性误答回归（第三阶段）。

这些用例用合成资料走真实 grounded_answer 路径，先确认会失败，再做最小兼容修复：

* 原文「F250007 仅允许 01」，模型带合法引用说「可以填 99」；
* 原文只列 01-03，模型列出 01-10；
* 引用 ID 合法但引用的单元与断言来源不匹配。
"""

import asyncio
from types import SimpleNamespace

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


def test_p0_1_code_value_not_in_cited_text_is_not_certain(db_session, monkeypatch):
    """P0-1：原文只允许 01，答案说可以填 99，不得为确定结论。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，F250007 可以填 99。",
        quoted="数据项编码：F250007；值域仅允许 01。",
    )
    assert result["answer_status"] == "needs_confirmation"
    assert any("99" in claim for claim in result["unsupported_claims"])


def test_p0_1_supported_code_value_stays_grounded(db_session, monkeypatch):
    """正例：答案用的码值确实在原文里。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，F250007 可以填 01。",
        quoted="数据项编码：F250007；值域仅允许 01。",
    )
    assert result["answer_status"] == "grounded"


def test_p0_3_partial_code_list_is_flagged(db_session, monkeypatch):
    """P0-3：原文只列 01-03（无「等」），答案列出 01-10，必须标缺项。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，合作方式码值可选 01、02、03、04、05、06、07、08、09、10。",
        quoted="数据项编码：F250007；值域：01 营销获客；02 联合贷款；03 支付结算。",
    )
    assert result["answer_status"] == "needs_confirmation"
    unsupported = " ".join(result["unsupported_claims"])
    assert any(code in unsupported for code in ("04", "05", "06", "07", "08", "09", "10"))


def test_p0_3_complete_code_list_stays_grounded(db_session, monkeypatch):
    """正例：答案码值都在原文里。"""

    result = _run(
        db_session, monkeypatch,
        answer="依据 [1]，合作方式码值可选 01、02、03。",
        quoted="数据项编码：F250007；值域：01 营销获客；02 联合贷款；03 支付结算。",
    )
    assert result["answer_status"] == "grounded"
