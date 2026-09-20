import hashlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.core.observability import build_log_event, current_request_id
from app.core.settings import get_settings
from app.models import ModelCallLog, ModelProfile, PromptTemplateVersion
from app.services.governance.audit import record_audit
from app.services.llm.base import (
    LLMRuntimeError,
    LLMService,
    StructuredResponse,
    sanitize_provider_error_detail,
)
from app.services.llm.execution_metadata import build_execution_metadata, stable_hash
from app.services.llm.providers import is_local_provider, normalize_provider_type
from app.services.security import ensure_external_allowed, redact_content
from .factory import get_interactive_llm_service, get_llm_service


logger = logging.getLogger("app.llm")


PROMPT_LABELS = {
    "requirement_field_candidate": "需求字段候选",
    "scenario_business_mapping": "场景业务口径",
    "scenario_technical_lineage": "场景技术溯源",
    "source_to_mart_mapping": "业务系统到监管集市",
    "mart_to_ybt_mapping": "监管集市到一表通",
    "source_recommendation_explanation": "来源字段推荐解释",
    "regulatory_field_explanation": "监管字段解释",
    "lineage_edge_explanation": "血缘关系业务解释",
}


@dataclass
class PromptRuntime:
    prompt_key: str
    version: int
    system_prompt: str
    user_template: str
    model_profile_id: int | None
    provider_type: str
    base_url: str | None
    model_name: str | None
    api_key_env_name: str | None
    local_only: bool
    config: dict[str, Any]


def partition_allowlisted_citations(
    citations: Iterable[Any] | None,
    allowed_refs: Iterable[str] | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Keep citations that resolve to the exact governed input allow-list."""

    if allowed_refs is None:
        return list(citations or []), []
    allowed = {str(item) for item in allowed_refs}
    accepted: list[Any] = []
    rejected: list[dict[str, Any]] = []
    for citation in citations or []:
        reference = _citation_reference(citation)
        if reference is not None and reference in allowed:
            accepted.append(citation)
            continue
        rejected.append({
            "citation": citation,
            "reason": "missing_reference" if reference is None else "out_of_scope",
            "reference": reference,
        })
    return accepted, rejected


def _citation_reference(citation: Any) -> str | None:
    if not isinstance(citation, dict):
        return None
    for key in ("citation_id", "source_ref", "fact_ref", "ref"):
        value = citation.get(key)
        if value not in (None, ""):
            return str(value)
    source_type = citation.get("source_type")
    fact_type = citation.get("fact_type")
    if source_type not in (None, "") and fact_type not in (None, ""):
        source_id = citation.get("source_id")
        return f"{source_type}:{source_id if source_id not in (None, '') else '-'}:{fact_type}"
    return None


def default_system_prompt(prompt_key: str) -> str:
    label = PROMPT_LABELS.get(prompt_key, prompt_key)
    return (
        f"你正在生成{label}。仅依据所给证据生成银行一表通业务需求草稿，"
        "不得虚构表字段，不得输出可执行 SQL；证据不足必须标记待确认。"
    )


def get_prompt_runtime(db, prompt_key: str) -> PromptRuntime:
    prompt = db.scalar(
        select(PromptTemplateVersion)
        .where(
            PromptTemplateVersion.prompt_key == prompt_key,
            PromptTemplateVersion.enabled.is_(True),
        )
        .order_by(PromptTemplateVersion.version_no.desc())
    )
    model = db.scalar(
        select(ModelProfile)
        .where(ModelProfile.enabled.is_(True))
        .order_by(ModelProfile.id)
    )
    settings = get_settings()
    provider = normalize_provider_type(model.provider_type if model else settings.llm_provider)
    local_only = bool(model.local_only) if model else provider == "mock" or is_local_provider(provider)
    return PromptRuntime(
        prompt_key=prompt_key,
        version=prompt.version_no if prompt else 1,
        system_prompt=prompt.system_prompt if prompt else default_system_prompt(prompt_key),
        user_template=prompt.user_prompt_template
        if prompt
        else "目标：{target}\n证据：{evidence}",
        model_profile_id=model.id if model else None,
        provider_type=provider,
        base_url=model.base_url if model else settings.llm_base_url,
        model_name=model.model_name if model else settings.llm_model,
        api_key_env_name=(model.api_key_env_name or (model.config_json or {}).get("api_key_env_name")) if model else settings.llm_api_key_env_name,
        local_only=local_only,
        config=dict(model.config_json or {}) if model else {},
    )


def get_runtime_llm_service(runtime: PromptRuntime, *, interactive: bool = False):
    if interactive:
        # A grounded answer degrades to its citations when the budget runs out,
        # so a retry would only double the time the user waits for the same
        # fallback.  The background/生成 path keeps its configured retries.
        return get_interactive_llm_service(
            runtime.provider_type,
            base_url=runtime.base_url,
            model=runtime.model_name,
            api_key_env_name=runtime.api_key_env_name,
            config=runtime.config,
            retry_count=0,
        )
    return get_llm_service(
        runtime.provider_type,
        base_url=runtime.base_url,
        model=runtime.model_name,
        api_key_env_name=runtime.api_key_env_name,
        config=runtime.config,
    )


def prepare_model_input(
    runtime: PromptRuntime,
    input_text: str,
    confidentiality_levels: list[str],
    *,
    db=None,
    project_id: int | None = None,
) -> str:
    try:
        for level in set(confidentiality_levels or ["internal"]):
            ensure_external_allowed(level, runtime.local_only)
    except ValueError:
        if db is not None:
            record_audit(
                db,
                action="external_model_data_denied",
                resource_type="model_profile",
                resource_id=runtime.model_profile_id,
                project_id=project_id,
                after={"provider": runtime.provider_type, "reason": "data_classification_policy"},
                result="denied",
            )
            db.commit()
        raise
    return input_text if runtime.local_only else redact_content(input_text)


def record_model_call(
    db,
    project_id,
    runtime,
    input_text,
    output,
    status="success",
    started=None,
    confidentiality="internal",
    retrieval_log_id=None,
    service: LLMService | None = None,
    error_type: str | None = None,
    http_status: int | None = None,
    error_detail: str | None = None,
    context_hash: str | None = None,
    context_complete: bool = True,
    context_budget: dict[str, Any] | None = None,
    citations: list[Any] | None = None,
    rejected_claims: list[Any] | None = None,
    execution_metadata: dict[str, Any] | None = None,
):
    metadata = service.last_call if service is not None else None
    request_hash = hashlib.sha256(input_text.encode()).hexdigest()
    execution_metadata = execution_metadata or build_execution_metadata(
        runtime,
        context_hash=context_hash or request_hash,
        context_complete=context_complete,
        context_budget=context_budget,
        output=output if status == "success" else None,
        citations=citations,
        rejected_claims=rejected_claims,
    )
    if isinstance(output, dict):
        output_summary = f"输出字段 {','.join(sorted(str(key) for key in output)[:20])}; 字符数 {len(str(output))}"
    else:
        output_summary = redact_content(str(output))[:300]
    db.add(
        ModelCallLog(
            project_id=project_id,
            model_profile_id=runtime.model_profile_id,
            retrieval_log_id=retrieval_log_id,
            prompt_key=runtime.prompt_key,
            prompt_version=runtime.version,
            provider=metadata.provider if metadata else normalize_provider_type(runtime.provider_type),
            model_name=metadata.model if metadata else runtime.model_name,
            skill_key=execution_metadata.get("skill_key"),
            skill_version=execution_metadata.get("skill_version"),
            execution_kind=execution_metadata.get("execution_kind"),
            request_hash=request_hash,
            context_hash=execution_metadata.get("context_hash") or request_hash,
            context_complete=execution_metadata.get("context_complete", context_complete),
            context_budget_json=execution_metadata.get("context_budget") or context_budget,
            input_summary=f"脱敏上下文长度 {len(input_text)}",
            output_summary=output_summary,
            output_hash=execution_metadata.get("output_hash"),
            citations_json=execution_metadata.get("citations") or citations or [],
            rejected_claims_json=execution_metadata.get("rejected_claims") or rejected_claims or [],
            execution_metadata_json=execution_metadata,
            status=status,
            latency_ms=metadata.latency_ms if metadata else int(
                (time.perf_counter() - (started or time.perf_counter())) * 1000
            ),
            token_usage_json=metadata.token_usage if metadata else {"usage_available": False},
            confidentiality_level=confidentiality,
            error_type=error_type,
            http_status=http_status if http_status is not None else (metadata.http_status if metadata else None),
            error_detail=sanitize_provider_error_detail(error_detail),
        )
    )


async def execute_runtime_chat_with_metadata(
    db,
    project_id: int,
    runtime: PromptRuntime,
    input_text: str,
    response_schema: type[StructuredResponse],
    *,
    confidentiality: str = "internal",
    retrieval_log_id: int | None = None,
    interactive: bool = False,
    context_complete: bool = True,
    context_budget: dict[str, Any] | None = None,
    allowed_citation_refs: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    service = get_runtime_llm_service(runtime, interactive=interactive)
    started = time.perf_counter()
    context_hash = stable_hash(input_text)
    try:
        validated = await service.chat_structured(runtime.system_prompt, input_text, response_schema)
        output = validated.model_dump(exclude_none=True)
        citations, rejected_citations = partition_allowlisted_citations(
            output.get("citations") if isinstance(output, dict) else None,
            allowed_citation_refs,
        )
        unsupported_claims = (
            output.get("unsupported_claims") if isinstance(output, dict) else None
        )
        rejected_claims = list(unsupported_claims or [])
        rejected_claims.extend(rejected_citations)
        if isinstance(output, dict) and allowed_citation_refs is not None:
            output["citations"] = citations
            output["citation_validation"] = {
                "accepted_count": len(citations),
                "rejected_count": len(rejected_citations),
            }
        metadata = build_execution_metadata(
            runtime,
            context_hash=context_hash,
            context_complete=context_complete,
            context_budget=context_budget,
            output=output,
            citations=citations,
            rejected_claims=rejected_claims,
        )
        record_model_call(
            db,
            project_id,
            runtime,
            input_text,
            output,
            started=started,
            confidentiality=confidentiality,
            retrieval_log_id=retrieval_log_id,
            service=service,
            context_hash=context_hash,
            context_complete=context_complete,
            context_budget=context_budget,
            execution_metadata=metadata,
        )
        return output, metadata
    except Exception as exc:
        error_type = exc.error_type if isinstance(exc, LLMRuntimeError) else type(exc).__name__
        is_runtime_error = isinstance(exc, LLMRuntimeError)
        error_detail = exc.detail if is_runtime_error else f"{type(exc).__name__}: {exc}"
        metadata = build_execution_metadata(
            runtime,
            execution_kind="degraded",
            context_hash=context_hash,
            context_complete=context_complete,
            context_budget=context_budget,
            degraded_reason=error_type,
        )
        setattr(exc, "execution_metadata", metadata)
        # Interactive endpoints convert the failure into a product answer; the
        # structured log line is what keeps that failure diagnosable later.
        logger.warning(
            json.dumps(
                build_log_event(
                    "model_call_failed",
                    level="WARNING",
                    logger_name="app.llm",
                    request_id=current_request_id(),
                    project_id=project_id,
                    prompt_key=runtime.prompt_key,
                    provider=getattr(service, "provider", None),
                    model=getattr(service, "model", None),
                    error_type=error_type,
                    http_status=exc.http_status if is_runtime_error else None,
                    error_detail=error_detail,
                    interactive=interactive,
                ),
                ensure_ascii=False,
            )
        )
        record_model_call(
            db,
            project_id,
            runtime,
            input_text,
            f"受控失败: {error_type}",
            status="failed",
            started=started,
            confidentiality=confidentiality,
            retrieval_log_id=retrieval_log_id,
            service=service,
            error_type=error_type,
            http_status=exc.http_status if is_runtime_error else None,
            error_detail=error_detail,
            context_hash=context_hash,
            context_complete=context_complete,
            context_budget=context_budget,
            execution_metadata=metadata,
        )
        db.commit()
        raise


async def execute_runtime_chat(
    db,
    project_id: int,
    runtime: PromptRuntime,
    input_text: str,
    response_schema: type[StructuredResponse],
    *,
    confidentiality: str = "internal",
    retrieval_log_id: int | None = None,
    interactive: bool = False,
    context_complete: bool = True,
    context_budget: dict[str, Any] | None = None,
    allowed_citation_refs: Iterable[str] | None = None,
) -> dict[str, Any]:
    output, _metadata = await execute_runtime_chat_with_metadata(
        db,
        project_id,
        runtime,
        input_text,
        response_schema,
        confidentiality=confidentiality,
        retrieval_log_id=retrieval_log_id,
        interactive=interactive,
        context_complete=context_complete,
        context_budget=context_budget,
        allowed_citation_refs=allowed_citation_refs,
    )
    return output
