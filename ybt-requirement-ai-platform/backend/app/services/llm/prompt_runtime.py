import hashlib
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.settings import get_settings
from app.models import ModelCallLog, ModelProfile, PromptTemplateVersion
from app.services.security import ensure_external_allowed, redact_content
from .factory import get_llm_service


PROMPT_LABELS = {
    "scenario_business_mapping": "场景业务口径",
    "scenario_technical_lineage": "场景技术溯源",
    "source_to_mart_mapping": "业务系统到监管集市",
    "mart_to_ybt_mapping": "监管集市到一表通",
    "source_recommendation_explanation": "来源字段推荐解释",
    "regulatory_field_explanation": "监管字段解释",
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
    provider = model.provider_type if model else settings.llm_provider
    local_only = bool(model.local_only) if model else provider in {
        "mock", "local_vllm", "local_ollama_compatible", "vllm", "ollama"
    }
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
        api_key_env_name=(model.config_json or {}).get("api_key_env_name") if model else settings.llm_api_key_env_name,
        local_only=local_only,
    )


def get_runtime_llm_service(runtime: PromptRuntime):
    return get_llm_service(
        runtime.provider_type,
        base_url=runtime.base_url,
        model=runtime.model_name,
        api_key_env_name=runtime.api_key_env_name,
    )


def prepare_model_input(
    runtime: PromptRuntime,
    input_text: str,
    confidentiality_levels: list[str],
) -> str:
    for level in set(confidentiality_levels or ["internal"]):
        ensure_external_allowed(level, runtime.local_only)
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
):
    db.add(
        ModelCallLog(
            project_id=project_id,
            model_profile_id=runtime.model_profile_id,
            retrieval_log_id=retrieval_log_id,
            prompt_key=runtime.prompt_key,
            prompt_version=runtime.version,
            request_hash=hashlib.sha256(input_text.encode()).hexdigest(),
            input_summary=f"脱敏上下文长度 {len(input_text)}",
            output_summary=redact_content(str(output))[:500],
            status=status,
            latency_ms=int(
                (time.perf_counter() - (started or time.perf_counter())) * 1000
            ),
            token_usage_json={},
            confidentiality_level=confidentiality,
        )
    )
