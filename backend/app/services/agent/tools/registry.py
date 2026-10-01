"""Controlled agent tool registry.

Design rules (execution spec §B):

* The planner may only select a ``tool_key`` that exists here. It can never
  invent a shell command, a raw SQL execution or an arbitrary HTTP call.
* Every tool declares its permissions, risk level, timeout, retry policy,
  read-only flag, human-confirmation requirement, evidence contract and audit
  fields. :func:`register_tool` refuses a spec that cannot be governed.
* Services in this codebase intentionally contain no permission logic, so a
  tool handler must re-enforce project scope + permission itself. The runtime
  performs the *declared* permission check before the handler runs; the handler
  additionally reuses the existing service's own authorization.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.models import AgentStep, AgentTask, Project
from app.services.auth.dependencies import Principal

TOOL_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,99}$")
RISK_LEVELS = ("low", "medium", "high", "critical")
RESULT_STATUSES = ("completed", "blocked", "waiting_human", "skipped", "failed")
# JSON-Schema keywords this project validates in-process (no jsonschema dependency).
SCHEMA_TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")


class ToolRegistryError(RuntimeError):
    """A tool spec (or a plan that references one) is not governable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ToolExecutionError(RuntimeError):
    """A tool handler refused or crashed. ``retryable`` drives the retry policy."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class AgentToolSpec:
    tool_key: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permissions: frozenset[str]
    risk_level: str
    timeout_seconds: int
    retry_policy: dict[str, Any]
    read_only: bool
    requires_human_confirmation: bool
    evidence_contract: dict[str, Any]
    audit_fields: tuple[str, ...]
    handler: Callable[["ToolContext"], Any] = field(compare=False, repr=False)
    # Which role(s) must approve the gate this tool opens (system policy, never the model).
    review_policy: dict[str, Any] | None = None
    handler: Callable[["ToolContext"], Any] = field(compare=False, repr=False)
    version: str = "1.0"
    # ``True`` when the tool needs the task's subject target field resolved first.
    requires_target_field: bool = False

    def as_dict(self) -> dict[str, Any]:
        """JSON projection for the API/UI and for planner prompt context."""

        return {
            "tool_key": self.tool_key,
            "display_name": self.display_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "required_permissions": sorted(self.required_permissions),
            "risk_level": self.risk_level,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy,
            "read_only": self.read_only,
            "requires_human_confirmation": self.requires_human_confirmation,
            "evidence_contract": self.evidence_contract,
            "audit_fields": list(self.audit_fields),
            "version": self.version,
        }


@dataclass
class ToolContext:
    """Everything a handler may use. Nothing else is passed to a tool."""

    db: Any
    principal: Principal
    project: Project
    task: AgentTask
    step: AgentStep
    tool_input: dict[str, Any]

    @property
    def project_id(self) -> int:
        return int(self.project.id)


@dataclass
class ToolResult:
    status: str = "completed"
    output: dict[str, Any] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    policy_evidence: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    # Grounded claims / policy comparisons produced under the AI-skill contract.
    claims: list[dict[str, Any]] = field(default_factory=list)
    policy_comparisons: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    model_metadata: dict[str, Any] = field(default_factory=dict)
    degraded_path: str | None = None
    human_gate: dict[str, Any] | None = None
    # Free-form step output kept for the next step's input (already redacted).
    step_output: dict[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise ToolRegistryError("invalid_tool_result_status", f"unknown tool result status: {self.status}")


_REGISTRY: dict[str, AgentToolSpec] = {}


def _schema_errors(schema: Any, *, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return [f"{label} must be an object"]
    if schema.get("type") != "object":
        errors.append(f"{label} must declare type=object")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        errors.append(f"{label}.properties must be an object")
    else:
        for name, definition in properties.items():
            if not isinstance(definition, dict):
                errors.append(f"{label}.properties.{name} must be an object")
                continue
            declared = definition.get("type")
            if isinstance(declared, list):
                if not set(declared) <= set(SCHEMA_TYPES):
                    errors.append(f"{label}.properties.{name} has an unknown type")
            elif declared is not None and declared not in SCHEMA_TYPES:
                errors.append(f"{label}.properties.{name} has an unknown type: {declared}")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        errors.append(f"{label}.required must be a list of strings")
    elif not set(required) <= set(properties):
        errors.append(f"{label}.required must be declared in properties")
    if schema.get("additionalProperties") not in (None, True, False):
        errors.append(f"{label}.additionalProperties must be a boolean")
    return errors


def validate_input(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """Minimal JSON-Schema subset validation used before a tool is invoked."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["input must be an object"]
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        value = payload.get(name)
        if value is None and name not in payload:
            errors.append(f"missing required input: {name}")
            continue
        definition = properties.get(name, {})
        if definition.get("type") == "array" and isinstance(definition.get("minItems"), int):
            if not isinstance(value, list) or len(value) < definition["minItems"]:
                errors.append(f"input {name} requires at least {definition['minItems']} item(s)")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(payload) - set(properties))
        if unknown:
            errors.append(f"unknown input: {', '.join(unknown)}")
    for name, definition in properties.items():
        if name not in payload:
            continue
        value = payload[name]
        expected = definition.get("type")
        if expected == "array" and not isinstance(value, list):
            errors.append(f"input {name} must be an array")
        elif expected == "string" and not isinstance(value, str):
            errors.append(f"input {name} must be a string")
        elif expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"input {name} must be an integer")
        elif expected == "object" and not isinstance(value, dict):
            errors.append(f"input {name} must be an object")
        elif expected == "boolean" and not isinstance(value, bool):
            errors.append(f"input {name} must be a boolean")
        if "enum" in definition and value not in definition["enum"]:
            errors.append(f"input {name} must be one of {definition['enum']}")
        if isinstance(definition.get("maxItems"), int) and isinstance(value, list):
            if len(value) > definition["maxItems"]:
                errors.append(f"input {name} accepts at most {definition['maxItems']} item(s)")
    return errors


def validate_spec(spec: AgentToolSpec) -> list[str]:
    """Governance checks a tool must satisfy to be registrable."""

    errors: list[str] = []
    if not TOOL_KEY_PATTERN.match(spec.tool_key):
        errors.append(f"tool_key must match {TOOL_KEY_PATTERN.pattern}: {spec.tool_key}")
    if not spec.display_name.strip():
        errors.append("display_name is required")
    if len(spec.description.strip()) < 8:
        errors.append("description must explain the governed capability")
    errors.extend(_schema_errors(spec.input_schema, label="input_schema"))
    from app.services.agent.gate_policy import validate_review_policy

    errors.extend(validate_review_policy(spec.review_policy))
    if spec.review_policy and not spec.requires_human_confirmation:
        errors.append("review_policy requires requires_human_confirmation")
    errors.extend(_schema_errors(spec.output_schema, label="output_schema"))
    if not spec.required_permissions:
        errors.append("required_permissions must declare at least one project permission")
    if any(not isinstance(item, str) or "." not in item for item in spec.required_permissions):
        errors.append("required_permissions entries must look like '<resource>.<action>'")
    if spec.risk_level not in RISK_LEVELS:
        errors.append(f"risk_level must be one of {RISK_LEVELS}")
    if not isinstance(spec.timeout_seconds, int) or not 1 <= spec.timeout_seconds <= 1800:
        errors.append("timeout_seconds must be between 1 and 1800")
    policy = spec.retry_policy or {}
    if not isinstance(policy, dict):
        errors.append("retry_policy must be an object")
    else:
        attempts = policy.get("max_attempts")
        if not isinstance(attempts, int) or not 1 <= attempts <= 5:
            errors.append("retry_policy.max_attempts must be between 1 and 5")
    if not isinstance(spec.read_only, bool):
        errors.append("read_only must be a boolean")
    if not isinstance(spec.requires_human_confirmation, bool):
        errors.append("requires_human_confirmation must be a boolean")
    if spec.requires_human_confirmation and spec.risk_level not in {"high", "critical"}:
        errors.append("a human-confirmation tool must be risk_level high or critical")
    if not spec.read_only and not spec.audit_fields:
        errors.append("a writing tool must declare audit_fields")
    contract = spec.evidence_contract or {}
    if not isinstance(contract, dict) or "fact_kinds" not in contract or "artifact_types" not in contract:
        errors.append("evidence_contract must declare fact_kinds and artifact_types")
    if not callable(spec.handler):
        errors.append("handler must be callable")
    return errors


def register_tool(spec: AgentToolSpec, *, replace: bool = False) -> AgentToolSpec:
    errors = validate_spec(spec)
    if errors:
        raise ToolRegistryError("invalid_tool_spec", f"{spec.tool_key}: " + "; ".join(errors))
    if spec.tool_key in _REGISTRY and not replace:
        raise ToolRegistryError("duplicate_tool_key", f"tool already registered: {spec.tool_key}")
    _REGISTRY[spec.tool_key] = spec
    return spec


def get_tool(tool_key: str) -> AgentToolSpec | None:
    return _REGISTRY.get(tool_key)


def require_tool(tool_key: str) -> AgentToolSpec:
    spec = _REGISTRY.get(tool_key)
    if spec is None:
        raise ToolRegistryError("unknown_tool", f"no registered tool: {tool_key}")
    return spec


def registered_tools() -> dict[str, AgentToolSpec]:
    return dict(_REGISTRY)


def tool_keys() -> list[str]:
    return sorted(_REGISTRY)


def tools_visible_for_permissions(permissions: Iterable[str]) -> list[dict[str, Any]]:
    """Registry listing filtered to what the actor could actually run."""

    granted = set(permissions)
    return [
        spec.as_dict()
        for _, spec in sorted(_REGISTRY.items())
        if set(spec.required_permissions) <= granted or spec.requires_human_confirmation
    ]


def reset_registry() -> None:
    """Test helper: drop every registration (builtins re-register on import)."""

    _REGISTRY.clear()
