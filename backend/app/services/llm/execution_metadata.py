"""Canonical execution metadata for model, mock, rule, and degraded results."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from app.services.llm.providers import is_local_provider, normalize_provider_type


ExecutionKind = Literal["real_model", "mock_model", "deterministic", "degraded"]


def provider_scope(provider_type: str | None) -> str:
    provider = normalize_provider_type(provider_type)
    if provider == "mock":
        return "mock"
    if is_local_provider(provider):
        return "local"
    return "cloud"


def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_execution_metadata(
    runtime,
    *,
    execution_kind: ExecutionKind | None = None,
    context_hash: str | None = None,
    context_complete: bool = True,
    context_budget: dict[str, Any] | None = None,
    output: Any = None,
    citations: list[Any] | None = None,
    rejected_claims: list[Any] | None = None,
    degraded_reason: str | None = None,
) -> dict[str, Any]:
    provider_type = normalize_provider_type(runtime.provider_type)
    kind: ExecutionKind = execution_kind or (
        "mock_model" if provider_type == "mock" else "real_model"
    )
    metadata: dict[str, Any] = {
        "execution_kind": kind,
        "provider": provider_scope(provider_type),
        "provider_type": provider_type,
        "model_name": runtime.model_name,
        "model_profile_id": runtime.model_profile_id,
        "prompt_key": runtime.prompt_key,
        "prompt_version": runtime.version,
        "skill_key": runtime.prompt_key,
        "skill_version": f"v{runtime.version}",
        "context_hash": context_hash,
        "context_complete": bool(context_complete),
        "context_budget": context_budget,
        "output_hash": stable_hash(output) if output is not None else None,
        "citations": citations or [],
        "rejected_claims": rejected_claims or [],
        "degraded_reason": degraded_reason,
    }
    return metadata


def deterministic_execution_metadata(
    skill_key: str,
    *,
    context_hash: str | None = None,
    context_complete: bool = True,
) -> dict[str, Any]:
    return {
        "execution_kind": "deterministic",
        "provider": "none",
        "provider_type": "deterministic",
        "model_name": None,
        "model_profile_id": None,
        "prompt_key": None,
        "prompt_version": None,
        "skill_key": skill_key,
        "skill_version": "deterministic",
        "context_hash": context_hash,
        "context_complete": bool(context_complete),
        "context_budget": None,
        "output_hash": None,
        "citations": [],
        "rejected_claims": [],
        "degraded_reason": None,
    }


def normalize_runtime_result(
    result: Any,
    runtime,
    *,
    context_hash: str | None = None,
    context_complete: bool = True,
    context_budget: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result
    return result, build_execution_metadata(
        runtime,
        context_hash=context_hash,
        context_complete=context_complete,
        context_budget=context_budget,
        output=result,
    )
