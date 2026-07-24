import os
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import get_settings
from app.models import ModelCallLog, ModelProfile
from app.services.auth.dependencies import CurrentPrincipal, Principal
from app.services.auth.permission_service import PermissionService
from app.services.embeddings.factory import get_embedding_service
from app.services.llm.base import LLMRuntimeError
from app.services.llm.factory import get_llm_service
from app.services.llm.providers import (
    is_local_provider,
    normalize_provider_type,
    provider_requires_api_key,
    sanitize_base_url,
    validate_env_name,
    validate_provider_url,
)


router = APIRouter(tags=["AI runtime"])


class ConnectionTestState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    tested_at: str
    error: str | None = None


class ModelCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    json_mode: bool = True
    max_output_tokens: int = Field(2048, ge=1, le=8192)
    temperature: float = Field(0.2, ge=0, le=2)
    timeout_seconds: int = Field(60, ge=1, le=180)
    retry_count: int = Field(2, ge=0, le=2)
    last_connection_test: ConnectionTestState | None = None


class ModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_name: str = Field(min_length=1, max_length=255)
    provider_type: str = "mock"
    base_url: str | None = None
    model_name: str | None = None
    embedding_model_name: str | None = None
    api_key_env_name: str | None = None
    local_only: bool = False
    enabled: bool = False
    config_json: ModelCapabilityConfig = Field(default_factory=ModelCapabilityConfig)

    @field_validator("api_key_env_name")
    @classmethod
    def _env_name(cls, value: str | None) -> str | None:
        return validate_env_name(value)

    @model_validator(mode="after")
    def _provider_config(self):
        self.provider_type = normalize_provider_type(self.provider_type)
        if self.provider_type == "mock":
            self.local_only = True
        elif is_local_provider(self.provider_type):
            if not self.local_only:
                raise ValueError("Local providers must set local_only=true")
        elif self.local_only:
            raise ValueError("Cloud providers cannot be marked local_only")
        self.base_url = validate_provider_url(self.base_url, local_only=self.local_only)
        return self


class ModelProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_name: str | None = Field(None, min_length=1, max_length=255)
    provider_type: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    embedding_model_name: str | None = None
    api_key_env_name: str | None = None
    local_only: bool | None = None
    config_json: ModelCapabilityConfig | None = None

    @field_validator("api_key_env_name")
    @classmethod
    def _env_name(cls, value: str | None) -> str | None:
        return validate_env_name(value)


class RuntimeTestRequest(BaseModel):
    profile_id: int | None = None


class ConnectionTestOutput(BaseModel):
    status: str
    message: str


@router.get("/ai-runtime/status")
def runtime_status(principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    profile = _active_profile(db)
    llm = _llm_status(profile)
    embedding = _embedding_status()
    vector = _vector_status()
    issues = [
        issue
        for issue in (
            _configuration_issue("llm", llm),
            _configuration_issue("embedding", embedding),
            _configuration_issue("vector_store", vector),
        )
        if issue
    ]
    response: dict[str, Any] = {
        "llm": llm,
        "embedding": embedding,
        "vector_store": vector,
        "issues": issues if PermissionService(db, principal).is_platform_admin() else [],
        "observability": _call_metrics(db),
    }
    return response


@router.post("/ai-runtime/test-chat")
async def test_chat(
    payload: RuntimeTestRequest,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(db, principal)
    profile = db.get(ModelProfile, payload.profile_id) if payload.profile_id else _active_profile(db)
    if payload.profile_id and profile is None:
        raise HTTPException(404, "Model profile not found")
    try:
        service = _profile_service(profile)
        result = await service.chat_structured(
            "Return only a small JSON object for a connection test.",
            'Return {"status":"ok","message":"连接成功"}. Do not use any project or user data.',
            ConnectionTestOutput,
        )
    except LLMRuntimeError as exc:
        _store_test_result(db, profile, "failed", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _store_test_result(db, profile, "success", None)
    metadata = service.last_call
    return {
        "status": result.status,
        "message": result.message,
        "provider": metadata.provider,
        "model": metadata.model,
        "latency_ms": metadata.latency_ms,
        "http_status": metadata.http_status,
        "token_usage": metadata.token_usage,
    }


@router.post("/ai-runtime/test-embedding")
def test_embedding(
    _: RuntimeTestRequest,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(db, principal)
    try:
        service = get_embedding_service()
        vector = service.embed_query("connection test")
    except LLMRuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not vector or not all(isinstance(value, (int, float)) for value in vector):
        raise HTTPException(status_code=503, detail="Embedding provider returned an invalid vector")
    return {
        "status": "ok",
        "dimension": len(vector),
        "latency_ms": service.last_call.latency_ms,
    }


@router.get("/model-profiles")
def model_profiles(principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(ModelProfile).order_by(ModelProfile.id)
    if not PermissionService(db, principal).is_platform_admin():
        query = query.where(ModelProfile.enabled.is_(True))
    return [_profile_response(item) for item in db.scalars(query).all()]


@router.post("/model-profiles", status_code=201)
def create_model_profile(
    payload: ModelProfileCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(db, principal)
    values = payload.model_dump()
    values["config_json"] = payload.config_json.model_dump()
    values["created_by"] = principal.username
    requested_enabled = values.pop("enabled")
    item = ModelProfile(**values, enabled=False)
    db.add(item)
    db.commit()
    db.refresh(item)
    if requested_enabled:
        _activate_profile(db, item)
    return _profile_response(item)


@router.patch("/model-profiles/{profile_id}")
def update_model_profile(
    profile_id: int,
    payload: ModelProfileUpdate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(db, principal)
    item = _profile_or_404(db, profile_id)
    merged = _profile_edit_values(item)
    changes = payload.model_dump(exclude_unset=True)
    if "config_json" in changes and payload.config_json is not None:
        changes["config_json"] = payload.config_json.model_dump()
    merged.update(changes)
    validated = ModelProfileCreate(**merged)
    for key, value in validated.model_dump(exclude={"enabled"}).items():
        setattr(item, key, value.model_dump() if isinstance(value, BaseModel) else value)
    db.commit()
    db.refresh(item)
    return _profile_response(item)


@router.post("/model-profiles/{profile_id}/activate")
def activate_model_profile(
    profile_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(db, principal)
    item = _profile_or_404(db, profile_id)
    _validate_activation(item)
    _activate_profile(db, item)
    return _profile_response(item)


@router.post("/model-profiles/{profile_id}/disable")
def disable_model_profile(
    profile_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(db, principal)
    item = _profile_or_404(db, profile_id)
    item.enabled = False
    db.commit()
    db.refresh(item)
    return _profile_response(item)


@router.post("/model-profiles/{profile_id}/test")
async def test_model_profile(
    profile_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await test_chat(RuntimeTestRequest(profile_id=profile_id), principal, db)


@router.get("/projects/{project_id}/model-calls")
def project_model_calls(
    project_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    prompt_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    predicates = [ModelCallLog.project_id == project_id]
    for column, value in (
        (ModelCallLog.prompt_key, prompt_key),
        (ModelCallLog.provider, provider),
        (ModelCallLog.model_name, model),
        (ModelCallLog.status, status),
    ):
        if value:
            predicates.append(column == value)
    if start_time:
        predicates.append(ModelCallLog.created_at >= start_time)
    if end_time:
        predicates.append(ModelCallLog.created_at <= end_time)
    total = db.scalar(select(func.count(ModelCallLog.id)).where(*predicates)) or 0
    rows = db.scalars(
        select(ModelCallLog)
        .where(*predicates)
        .order_by(ModelCallLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_model_call_response(item) for item in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def _require_admin(db: Session, principal: Principal) -> None:
    if not PermissionService(db, principal).is_platform_admin():
        raise HTTPException(status_code=403, detail="Platform administrator permission is required")


def _active_profile(db: Session) -> ModelProfile | None:
    return db.scalar(select(ModelProfile).where(ModelProfile.enabled.is_(True)).order_by(ModelProfile.id))


def _profile_service(profile: ModelProfile | None):
    settings = get_settings()
    if profile is None:
        return get_llm_service()
    return get_llm_service(
        profile.provider_type,
        base_url=profile.base_url,
        model=profile.model_name,
        api_key_env_name=profile.api_key_env_name,
        config=profile.config_json,
    )


def _llm_status(profile: ModelProfile | None) -> dict[str, Any]:
    settings = get_settings()
    provider = normalize_provider_type(profile.provider_type if profile else settings.llm_provider)
    base_url = profile.base_url if profile else settings.llm_base_url
    model = profile.model_name if profile else settings.llm_model
    env_name = profile.api_key_env_name if profile else settings.llm_api_key_env_name
    local = bool(profile.local_only) if profile else is_local_provider(provider)
    present = bool(os.getenv(env_name or "", settings.llm_api_key))
    configured = (
        provider == "mock"
        or bool(base_url and model and (present or not provider_requires_api_key(provider)))
    )
    safe_url = sanitize_base_url(base_url)
    return {
        "provider": provider,
        "model": "mock-llm" if provider == "mock" else model,
        "base_url": safe_url,
        "base_url_host": urlsplit(safe_url).hostname if safe_url else None,
        "profile_id": profile.id if profile else None,
        "is_mock": provider == "mock",
        "is_local": local,
        "api_key_env_name": env_name,
        "api_key_present": present,
        "configuration_status": "configured" if configured else "misconfigured",
        "last_connection_test": (profile.config_json or {}).get("last_connection_test") if profile else None,
    }


def _embedding_status() -> dict[str, Any]:
    settings = get_settings()
    provider = normalize_provider_type(settings.embedding_provider)
    local = is_local_provider(provider)
    present = bool(settings.resolved_embedding_api_key)
    configured = (
        provider == "mock"
        or bool(settings.embedding_base_url and settings.embedding_model and (present or not provider_requires_api_key(provider)))
    )
    safe_url = sanitize_base_url(settings.embedding_base_url)
    return {
        "provider": provider,
        "model": "mock-embedding" if provider == "mock" else settings.embedding_model,
        "base_url": safe_url,
        "base_url_host": urlsplit(safe_url).hostname if safe_url else None,
        "is_mock": provider == "mock",
        "is_local": local,
        "api_key_env_name": settings.embedding_api_key_env_name,
        "api_key_present": present,
        "configuration_status": "configured" if configured else "misconfigured",
    }


def _vector_status() -> dict[str, Any]:
    settings = get_settings()
    configured = settings.vector_store_provider == "mock" or bool(settings.milvus_uri)
    return {
        "provider": settings.vector_store_provider,
        "is_mock": settings.vector_store_provider == "mock",
        "configuration_status": "configured" if configured else "misconfigured",
    }


def _configuration_issue(component: str, status: dict[str, Any]) -> dict[str, str] | None:
    if status["configuration_status"] == "configured":
        return None
    return {"component": component, "code": "configuration_incomplete", "message": f"{component} configuration is incomplete"}


def _call_metrics(db: Session) -> dict[str, Any]:
    latest_success = db.scalar(select(ModelCallLog).where(ModelCallLog.status == "success").order_by(ModelCallLog.id.desc()))
    latest_failure = db.scalar(select(ModelCallLog).where(ModelCallLog.status == "failed").order_by(ModelCallLog.id.desc()))
    average_latency = db.scalar(select(func.avg(ModelCallLog.latency_ms))) or 0
    return {
        "last_success_at": latest_success.created_at if latest_success else None,
        "last_failure_at": latest_failure.created_at if latest_failure else None,
        "average_latency_ms": round(float(average_latency), 2),
        "recent_token_usage": latest_success.token_usage_json if latest_success else {"usage_available": False},
    }


def _store_test_result(db: Session, profile: ModelProfile | None, status: str, error: str | None) -> None:
    if profile is None:
        return
    profile.config_json = {
        **(profile.config_json or {}),
        "last_connection_test": {
            "status": status,
            "tested_at": datetime.now().astimezone().isoformat(),
            "error": error[:200] if error else None,
        },
    }
    db.commit()


def _profile_response(item: ModelProfile) -> dict[str, Any]:
    return {
        "id": item.id,
        "profile_name": item.profile_name,
        "provider_type": normalize_provider_type(item.provider_type),
        "base_url": sanitize_base_url(item.base_url),
        "base_url_host": urlsplit(sanitize_base_url(item.base_url)).hostname if item.base_url else None,
        "model_name": item.model_name,
        "embedding_model_name": item.embedding_model_name,
        "api_key_env_name": item.api_key_env_name,
        "api_key_present": bool(os.getenv(item.api_key_env_name or "")),
        "local_only": item.local_only,
        "enabled": item.enabled,
        "config_json": item.config_json,
        "created_by": item.created_by,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _profile_edit_values(item: ModelProfile) -> dict[str, Any]:
    return {
        "profile_name": item.profile_name,
        "provider_type": item.provider_type,
        "base_url": item.base_url,
        "model_name": item.model_name,
        "embedding_model_name": item.embedding_model_name,
        "api_key_env_name": item.api_key_env_name,
        "local_only": item.local_only,
        "enabled": item.enabled,
        "config_json": item.config_json or {},
    }


def _validate_activation(item: ModelProfile) -> None:
    provider = normalize_provider_type(item.provider_type)
    if provider == "mock":
        return
    if not item.base_url or not item.model_name:
        raise HTTPException(status_code=422, detail="Base URL and model name are required before activation")
    if provider_requires_api_key(provider) and not os.getenv(item.api_key_env_name or ""):
        raise HTTPException(status_code=422, detail=f"API key environment variable {item.api_key_env_name or '(missing)'} is not configured")


def _activate_profile(db: Session, item: ModelProfile) -> None:
    _validate_activation(item)
    for active in db.scalars(select(ModelProfile).where(ModelProfile.enabled.is_(True))).all():
        active.enabled = False
    item.enabled = True
    db.commit()
    db.refresh(item)


def _profile_or_404(db: Session, profile_id: int) -> ModelProfile:
    item = db.get(ModelProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Model profile not found")
    return item


def _model_call_response(item: ModelCallLog) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "model_profile_id": item.model_profile_id,
        "retrieval_log_id": item.retrieval_log_id,
        "prompt_key": item.prompt_key,
        "prompt_version": item.prompt_version,
        "provider": item.provider,
        "model_name": item.model_name,
        "status": item.status,
        "latency_ms": item.latency_ms,
        "token_usage": item.token_usage_json,
        "confidentiality_level": item.confidentiality_level,
        "error_type": item.error_type,
        "created_at": item.created_at,
        "input_summary": item.input_summary,
        "output_summary": item.output_summary,
    }


__all__ = ["ModelProfileCreate", "sanitize_base_url"]
