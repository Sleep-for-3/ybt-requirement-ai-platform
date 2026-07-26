#!/usr/bin/env python3
"""Deterministic local OpenAI-compatible provider for tests and smoke only."""

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Fake OpenAI-compatible Provider")


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]


class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]


@app.post("/v1/chat/completions")
def chat(payload: ChatRequest) -> dict:
    content = {
        "status": "ok",
        "message": "连接成功",
        "business_definition": "基于脱敏测试证据形成的业务口径，需人工确认。",
        "processing_logic": "按已确认来源字段直接取值并执行码值转换。",
        "processing_logic_type": "direct",
        "source_system_summary": "脱敏测试源系统",
        "source_tables_summary": "demo_source",
        "source_fields_summary": "demo_field",
        "business_rule": "仅依据所给证据生成测试业务规则。",
        "business_to_mart_rule": "测试源字段进入监管集市并保留证据。",
        "mart_to_ybt_rule": "测试集市字段映射到一表通目标字段。",
        "mart_table_summary": "demo_mart",
        "mart_field_summary": "demo_field",
        "filter_condition": "按有效状态过滤。",
        "join_condition": "按脱敏业务主键关联。",
        "priority_rule": "已确认来源优先。",
        "merge_rule": "冲突进入人工确认。",
        "code_mapping_rule": "按测试代码集转换。",
        "null_handling_rule": "空值进入待确认清单。",
        "exception_rule": "非法值标记异常。",
        "quality_check_rule": "校验空值率和枚举覆盖率。",
        "reporting_condition": "符合测试报送范围。",
        "validation_rule": "校验非空和代码合法性。",
        "answer": "现有证据支持该字段采用已引用的脱敏测试来源，具体口径仍需人工确认。",
        "supported_claims": ["回答仅依据已提供的测试证据。"],
        "unsupported_claims": [],
        "source_system_candidates": ["DEMO"],
        "source_table_candidates": ["demo_source"],
        "source_field_candidates": ["demo_field"],
        "east_reference_summary": "脱敏 EAST 测试摘要。",
        "sql_reference_summary": "脱敏 SQL 证据摘要。",
        "validation_notes": "需人工复核。",
        "template_reference_summary": "测试模板边界。",
        "db_query_summary": "测试数据质量摘要。",
        "data_quality_notes": "检查空值率。",
        "evidence_completeness": "medium",
        "risk_points": ["仅用于本地协议验证。"],
        "questions_for_human": ["请人工确认。"],
        "open_questions": ["请人工确认测试口径。"],
        "confidence_level": "medium",
        "final_content_draft": "本地 Fake Provider 生成的脱敏测试草稿，仅用于协议兼容验证。",
    }
    return {
        "id": "fake-chat-completion",
        "object": "chat.completion",
        "model": payload.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": __import__("json").dumps(content, ensure_ascii=False)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50},
    }


@app.post("/v1/embeddings")
def embeddings(payload: EmbeddingRequest) -> dict:
    inputs = payload.input if isinstance(payload.input, list) else [payload.input]
    return {
        "object": "list",
        "model": payload.model,
        "data": [{"index": index, "embedding": [0.1 + index * 0.001] * 8} for index, _ in enumerate(inputs)],
        "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=18080)
