import hashlib

from app.models import ModelCallLog
from app.services.governance.audit import record_audit
from app.services.llm.base import LLMRuntimeError
from app.services.security import ensure_external_allowed, redact_content


CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def record_embedding_call(
    db,
    project_id: int,
    service,
    texts: list[str],
    vectors: list[list[float]],
    *,
    confidentiality_level: str = "internal",
) -> None:
    metadata = service.last_call
    request_material = "|".join(hashlib.sha256(text.encode()).hexdigest() for text in texts)
    db.add(ModelCallLog(
        project_id=project_id,
        model_profile_id=None,
        retrieval_log_id=None,
        prompt_key="embedding",
        prompt_version=1,
        provider=metadata.provider,
        model_name=metadata.model,
        request_hash=hashlib.sha256(request_material.encode()).hexdigest(),
        input_summary=f"Embedding 文本数量 {len(texts)}；总字符数 {sum(len(text) for text in texts)}",
        output_summary=f"向量数量 {len(vectors)}；维度 {len(vectors[0]) if vectors else 0}",
        status="success",
        latency_ms=metadata.latency_ms,
        token_usage_json=metadata.token_usage,
        confidentiality_level=confidentiality_level,
        error_type=None,
    ))


def embed_with_observability(
    db,
    project_id: int,
    service,
    texts: list[str],
    confidentiality_levels: list[str] | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    levels = confidentiality_levels or ["internal"] * len(texts)
    if len(levels) != len(texts):
        raise ValueError("Embedding confidentiality metadata does not match input count")
    local_only = bool(getattr(service, "local_only", False))
    ensure_embedding_external_allowed(
        db,
        project_id,
        service,
        levels,
        persist_denial=False,
    )
    outbound = texts if local_only else [redact_content(text) for text in texts]
    confidentiality = max(levels, key=lambda item: CLASSIFICATION_RANK.get(item, 1))
    try:
        vectors = service.embed_texts(outbound)
    except Exception as exc:
        metadata = service.last_call
        error_type = exc.error_type if isinstance(exc, LLMRuntimeError) else type(exc).__name__
        request_material = "|".join(hashlib.sha256(text.encode()).hexdigest() for text in outbound)
        db.add(ModelCallLog(
            project_id=project_id,
            prompt_key="embedding",
            prompt_version=1,
            provider=metadata.provider,
            model_name=metadata.model,
            request_hash=hashlib.sha256(request_material.encode()).hexdigest(),
            input_summary=f"Embedding 文本数量 {len(outbound)}；总字符数 {sum(len(text) for text in outbound)}",
            output_summary=f"受控失败: {error_type}",
            status="failed",
            latency_ms=metadata.latency_ms,
            token_usage_json=metadata.token_usage,
            confidentiality_level=confidentiality,
            error_type=error_type,
        ))
        db.flush()
        raise
    record_embedding_call(
        db,
        project_id,
        service,
        outbound,
        vectors,
        confidentiality_level=confidentiality,
    )
    return vectors


def ensure_embedding_external_allowed(
    db,
    project_id: int,
    service,
    confidentiality_levels: list[str],
    *,
    persist_denial: bool,
) -> None:
    try:
        for level in set(confidentiality_levels):
            ensure_external_allowed(level, bool(getattr(service, "local_only", False)))
    except ValueError:
        record_audit(
            db,
            action="external_embedding_data_denied",
            resource_type="embedding_provider",
            project_id=project_id,
            after={"provider": service.last_call.provider, "reason": "data_classification_policy"},
            result="denied",
        )
        if persist_denial:
            db.commit()
        else:
            db.flush()
        raise
