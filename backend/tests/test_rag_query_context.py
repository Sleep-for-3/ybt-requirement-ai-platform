import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.api.knowledge_rag import AskRequest
from app.services.rag import query_understanding as planning
from app.services.rag.context_assembly import assemble_context
from app.services.retrieval import reranker


def item(identity, text="short", roles=(), authority=5):
    return {"knowledge_unit_id": identity, "content": text,
            "evidence_roles": list(roles), "authority_rank": authority}


def test_assembly_reserves_roles_after_ranking_and_keeps_long_clause_whole():
    rows = [item(1, roles=["a"]), item(2, "长条款" * 5000, ["b"]),
            item(3, roles=["b"]), item(4)]
    selected, report = assemble_context(rows, budget=40, roles=["a", "b", "c"])
    assert [row["knowledge_unit_id"] for row in selected][:2] == [1, 3]
    assert 2 in report["budget_excluded_ids"]
    assert report["missing_roles"] == ["c"]
    assert report["estimated_tokens"] <= 40
    assert rows[1]["content"] == "长条款" * 5000


@pytest.mark.parametrize("history", [
    [{"role": "system", "content": "x"}],
    [{"role": "user", "content": "x"}],
    [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}],
    [{"role": "user", "content": " "}, {"role": "assistant", "content": "y"}],
    [{"role": "user", "content": "x" * 12000}, {"role": "assistant", "content": "y"}],
    [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}] * 7,
])
def test_api_rejects_unbounded_or_invalid_history(history):
    with pytest.raises(ValueError):
        AskRequest(query="q", history=history)


@dataclass
class Runtime:
    system_prompt: str = "test"


def planner(monkeypatch, output=None, fail=False):
    calls = []
    monkeypatch.setattr(planning, "get_prompt_runtime", lambda *a, **k: Runtime())
    monkeypatch.setattr(planning, "prepare_model_input", lambda runtime, payload, *a, **k: payload)

    async def generate(*args, **kwargs):
        calls.append(args[3])
        if fail:
            await asyncio.sleep(.03)
        return output or {}, {}

    monkeypatch.setattr(planning, "execute_runtime_chat_with_metadata", generate)
    return calls


def run_plan(monkeypatch, query, history=(), output=None, fail=False, enabled=True):
    calls = planner(monkeypatch, output, fail)
    settings = SimpleNamespace(rag_query_planning_enabled=enabled,
                               rag_query_planner_timeout_seconds=.01)
    db = SimpleNamespace(get=lambda *a: None)
    plan = asyncio.run(planning.plan_query(db, 1, query, history, settings))
    return plan, calls


def test_simple_and_literal_questions_do_not_call_planner(monkeypatch):
    plan, calls = run_plan(monkeypatch, "合作方式如何填报")
    assert plan["source"] == "original" and not calls
    plan, calls = run_plan(monkeypatch, "合作方式如何填报？码值是什么？")
    assert plan["source"] == "literal" and not calls
    assert len(plan["queries"]) <= 4


def test_followup_only_forwards_user_text_and_retains_original(monkeypatch):
    plan, calls = run_plan(monkeypatch, "那它的码值呢", [
        {"role": "user", "content": "合作方式F250007"},
        {"role": "assistant", "content": "private assistant evidence"}],
        {"subqueries": [{"role": "码值", "query": "F250007码值"}]})
    assert len(calls) == 1
    assert "private assistant evidence" not in calls[0]
    assert plan["queries"][0]["query"] == "那它的码值呢"
    assert plan["queries"][1]["query"] == "F250007码值"


def test_timeout_and_invented_fields_fall_back_to_original(monkeypatch):
    plan, calls = run_plan(monkeypatch, "分别如何填报", fail=True)
    assert len(calls) == 1 and plan["degraded_reason"] == "TimeoutError"
    assert len(plan["queries"]) == 1
    plan, calls = run_plan(monkeypatch, "分别如何填报",
                          output={"subqueries": [{"role": "a", "query": "F999999"}]})
    assert plan["degraded_reason"] == "ValueError" and len(plan["queries"]) == 1


def test_ambiguous_followup_requests_clarification(monkeypatch):
    plan, calls = run_plan(monkeypatch, "分别如何填报",
                          output={"clarification_question": "请明确报送体系"})
    assert len(calls) == 1 and plan["clarification_question"]
    assert len(plan["queries"]) == 1
    plan, calls = run_plan(monkeypatch, "分别如何填报", enabled=False)
    assert not calls and plan["source"] == "original"


def test_fusion_detects_changes_deduplicates_and_preserves_authority():
    a, b = item(1, authority=6), item(2, authority=5)
    rows = planning.merge_role_results([("original", [a, a, b]), ("码值", [b])])
    assert [row["knowledge_unit_id"] for row in rows] == [1, 2]
    assert rows[1]["evidence_roles"] == ["original", "码值"]
    with pytest.raises(ValueError, match="变化"):
        planning.merge_role_results([("a", [a]), ("b", [{**a, "content": "changed"}])])


def test_relevance_order_is_opt_in_and_raw_logit_is_preserved(monkeypatch):
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *a: (
        SimpleNamespace(rerank=lambda **k: [-2, 5]), None))
    settings = SimpleNamespace(reranker_enabled=True)
    rows = [item(1, authority=6), item(2, authority=5)]
    assert reranker.rerank_items(rows, "query", settings).items[0]["knowledge_unit_id"] == 1
    settings.reranker_order = "relevance"
    result = reranker.rerank_items(rows, "query", settings)
    assert result.items[0]["knowledge_unit_id"] == 2
    assert result.items[0]["raw_rerank_score"] == 5
