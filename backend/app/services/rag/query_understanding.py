"""Bounded query planning; prior answers never become retrieval evidence."""
import asyncio
from dataclasses import replace
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.services.code_extraction import extract_field_codes
from app.services.knowledge_evidence import evidence_runtime
from app.services.llm.prompt_runtime import (
    get_prompt_runtime, prepare_model_input, execute_runtime_chat_with_metadata,
)


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


def validate_history(history):
    messages = TypeAdapter(list[HistoryMessage]).validate_python(history or [])
    if len(messages) > 12 or len(messages) % 2:
        raise ValueError("历史对话最多六轮，且必须为完整问答")
    if sum(len(message.content) for message in messages) > 12000:
        raise ValueError("历史对话总长不能超过12000字符")
    if any(message.role != ("user" if index % 2 == 0 else "assistant")
           or not message.content.strip() for index, message in enumerate(messages)):
        raise ValueError("历史对话必须按用户、助手交替排列，且内容不能为空")
    return messages


class Subquery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=2000)


class QueryPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subqueries: list[Subquery] = Field(default_factory=list, max_length=3)
    clarification_question: str | None = Field(default=None, max_length=300)


async def plan_query(db, project_id, query, history, settings, *, model_profile_id=None):
    messages = validate_history(history)
    plan = {"original_query": query, "queries": [{"query": query, "role": "original"}],
            "source": "original", "clarification_question": None, "degraded_reason": None}
    if not settings.rag_query_planning_enabled:
        return plan
    # Reuse the existing literal clause planner for explicit multi-part questions.
    from app.services.retrieval.planned_search import query_plan
    literal = query_plan(query)
    if len(literal["queries"]) > 1:
        plan["queries"].extend({"query": part, "role": f"part-{index}"}
                               for index, part in enumerate(literal["queries"][1:], 1))
        plan["source"] = "literal"
        return plan
    followup = bool(messages and re.match(r"^(那|它|这个|该|上述|前者|后者|还有|那么)", query.strip()))
    compound = bool(re.search(r"分别|各自|对比|差异|同时", query))
    if not followup and not compound:
        return plan
    # Only user questions are needed to resolve references. Earlier generated
    # answers may contain sensitive evidence and must not be forwarded again.
    user_questions = [message.content for message in messages if message.role == "user"]
    try:
        runtime = evidence_runtime(get_prompt_runtime(
            db, "rag_query_plan", model_profile_id=model_profile_id))
        runtime = replace(runtime, system_prompt=runtime.system_prompt + (
            "\n仅将当前问题改写为最多三个可独立检索的子问题，每个子问题附role。"
            "历史用户问题仅用于指代消解，不是事实或证据。不得推断缺少的体系、版本或字段。"
            "有多个可能指代时返回clarification_question，不猜测。"
            '仅输出JSON：{"subqueries":[{"role":"...","query":"..."}],"clarification_question":null}。'))
        payload = json.dumps({"query": query, "prior_user_questions": user_questions}, ensure_ascii=False)
        from app.models import Project
        project = db.get(Project, project_id)
        level = getattr(project, "confidentiality_level", None) or "internal"
        prepared = prepare_model_input(runtime, payload, [level], db=db, project_id=project_id)
        output, metadata = await asyncio.wait_for(
            execute_runtime_chat_with_metadata(
                db, project_id, runtime, prepared, QueryPlanOutput,
                confidentiality=level, interactive=True),
            timeout=settings.rag_query_planner_timeout_seconds)
        parsed = QueryPlanOutput.model_validate(output)
        allowed_codes = extract_field_codes("\n".join([query, *user_questions]))
        if any(extract_field_codes(part.query) - allowed_codes for part in parsed.subqueries):
            raise ValueError("planner_invented_identifier")
        plan["clarification_question"] = parsed.clarification_question
        if not parsed.clarification_question:
            seen = {query}
            for part in parsed.subqueries:
                if part.query.strip() and part.query.strip() not in seen:
                    plan["queries"].append({"query": part.query.strip(), "role": part.role})
                    seen.add(part.query.strip())
        plan.update(source="model", execution_metadata=metadata)
    except Exception as error:
        plan["degraded_reason"] = type(error).__name__
    return plan


def merge_role_results(rounds):
    merged = {}
    scores = {}
    for role, items in rounds:
        seen = set()
        for rank, item in enumerate(items, 1):
            unit_id = item["knowledge_unit_id"]
            if unit_id in seen:
                continue
            seen.add(unit_id)
            previous = merged.get(unit_id)
            if previous and any(previous.get(key) != item.get(key)
                                for key in ("content_hash", "document_version_id", "content")):
                raise ValueError("检索期间资料发生变化，请重新提问")
            if previous is None:
                merged[unit_id] = {**item, "evidence_roles": []}
            if role not in merged[unit_id]["evidence_roles"]:
                merged[unit_id]["evidence_roles"].append(role)
            scores[unit_id] = scores.get(unit_id, 0) + 1 / (60 + rank)
    return sorted(merged.values(), key=lambda item: (-item.get("authority_rank", 0),
                                                    -scores[item["knowledge_unit_id"]],
                                                    item["knowledge_unit_id"]))
