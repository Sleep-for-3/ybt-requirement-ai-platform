import hashlib

from app.services.llm.base import LLMService


class MockLLMService(LLMService):
    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        return {
            "business_to_mart_rule": "建议从客户主数据系统抽取目标字段，按监管集市客户维度统一代码值和空值处理规则。",
            "mart_to_ybt_rule": "监管集市字段直接映射至一表通目标字段；如存在监管代码集，需按最新一表通代码表转换。",
            "source_system_candidates": ["ECIF", "信贷"],
            "source_table_candidates": ["ecif_customer", "loan_contract"],
            "source_field_candidates": ["cert_type", "customer_id"],
            "east_reference_summary": "历史 EAST 口径显示该字段通常来自客户基础信息，并需要保留原始代码与监管标准代码的映射关系。",
            "sql_reference_summary": "相关 SQL 片段显示客户表与业务合同表通过 customer_id 关联，并包含有效状态过滤条件。",
            "validation_notes": "需人工确认代码值范围、空值处理、以及业务系统和监管集市字段的一致性。",
            "confidence_level": "medium",
            "risk_points": ["历史口径和监管集市 SQL 可能存在字段命名不一致。"],
            "questions_for_human": ["请确认目标字段是否必须使用一表通最新监管代码集。"],
        }

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embedding(text) for text in texts]


def _hash_embedding(text: str, dimensions: int = 64) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for index in range(dimensions):
        byte = digest[index % len(digest)]
        values.append((byte / 255.0) - 0.5)
    return values
