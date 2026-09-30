import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import requirement_generation_worker as worker


@pytest.mark.parametrize("overflow", [True, False])
def test_correction_rechecks_actual_bytes_before_each_model_attempt(monkeypatch, overflow):
    frozen = {"field_ids": [1], "sections": ["business"], "fields": [{"target": {"id": 1}}], "evidence": [], "physical_sources": []}
    first_input = json.dumps({**frozen, "section": "business"}, ensure_ascii=False, sort_keys=True)
    budget = len(first_input.encode("utf-8")) + 1 if overflow else 64000
    runtime = SimpleNamespace(config={"requirement_max_input_bytes": budget}, system_prompt="固定系统提示",
                              provider_type="mock", model_name="isolated", version=1)
    calls = []
    monkeypatch.setattr(worker, "get_prompt_runtime", lambda *args: runtime)
    monkeypatch.setattr(worker, "prepare_model_input", lambda runtime, prompt, *args, **kwargs: prompt)
    async def execute(db, project_id, runtime, prompt, schema, **kwargs):
        calls.append((prompt, dict(kwargs["context_budget"])))
        return {"final_content": "待核验候选"}, {"execution_kind": "mock_model"}
    monkeypatch.setattr(worker, "execute_runtime_chat", execute)
    monkeypatch.setattr(worker, "check_candidate_compliance", lambda context, candidate: ["范围外字段"] if len(calls) == 1 else [])
    args = (None, SimpleNamespace(input_json=frozen), SimpleNamespace(id=7, field_id=1, section="business"),
            SimpleNamespace(id=1, confidentiality_level="internal"))
    if overflow:
        with pytest.raises(HTTPException, match="纠错后的完整输入超过模型预算"):
            worker.generate_candidate(*args)
        assert len(calls) == 1
    else:
        candidate = worker.generate_candidate(*args)
        assert len(calls) == 2
        assert candidate["execution_metadata"]["self_correction_attempts"] == 2
        assert calls[1][1]["used"] > calls[0][1]["used"]
    for prompt, recorded in calls:
        assert recorded["used"] == len(prompt.encode("utf-8")) <= recorded["limit"]
    assert "section" not in frozen
