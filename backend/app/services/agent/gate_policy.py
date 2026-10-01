"""Human-gate routing policy.

Which role must approve which gate is **system configuration**, never the model's
choice. A gate key maps to a policy:

``single``
    one review task, assigned by role, approved by one reviewer.
``all``
    one review task per role; the gate only completes when every role approved
    (dual approval for high-impact changes).
``any``
    one review task per role; the first approval completes the gate and closes the rest.

A tool may declare its own ``review_policy`` in the registry; a step's ``gate_key``
always wins, because a gate is more specific than the tool that opened it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.auth.permission_service import PROJECT_ROLE_PERMISSIONS

MODES: tuple[str, ...] = ("single", "all", "any")
# Which permission a routed role needs to act on its gate (the permission follows the role).
ROLE_GATE_PERMISSION: dict[str, str] = {
    "project_manager": "final.review",
    "final_reviewer": "final.review",
    "technical_reviewer": "technical.review",
    "business_reviewer": "business.review",
    "business_analyst": "business.edit",
    "technical_analyst": "technical.edit",
    "data_developer": "technical.edit",
}
# The permission a gate needs when no routed role is available.
FALLBACK_GATE_PERMISSION = "final.review"


def permission_for_role(role: str | None) -> str:
    return ROLE_GATE_PERMISSION.get(str(role or ""), FALLBACK_GATE_PERMISSION)
DEFAULT_GATE_ROLE = "project_manager"
DEFAULT_POLICY: dict[str, object] = {"mode": "single", "roles": (DEFAULT_GATE_ROLE,)}
MAX_GATE_ROLES = 4

# Gate key → policy. Keys are opened by request_human_confirmation or by a gated tool.
GATE_POLICY: dict[str, dict[str, object]] = {
    "subject_clarification": {"mode": "single", "roles": ("business_analyst",)},
    "requirement_candidate_adoption": {"mode": "single", "roles": ("project_manager",)},
    "mapping_recommendation_adoption": {"mode": "single", "roles": ("technical_reviewer",)},
    "policy_conflict_review": {"mode": "single", "roles": ("business_reviewer",)},
    "document_publish_review": {"mode": "any", "roles": ("project_manager", "final_reviewer")},
    "sql_impact_review": {"mode": "all", "roles": ("technical_reviewer", "business_reviewer")},
}


@dataclass(frozen=True)
class GatePolicy:
    mode: str
    roles: tuple[str, ...]
    source: str  # gate policy table | tool spec | default

    @property
    def is_dual(self) -> bool:
        return self.mode == "all" and len(self.roles) > 1

    @property
    def permissions(self) -> tuple[str, ...]:
        return tuple(permission_for_role(role) for role in self.roles)

    def as_dict(self) -> dict[str, object]:
        return {"mode": self.mode, "roles": list(self.roles), "source": self.source,
                "permissions": list(self.permissions)}


def normalize_policy(raw: object) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode") or "single")
    roles = raw.get("roles") or ([raw["role"]] if raw.get("role") else [])
    if mode not in MODES:
        return None
    cleaned = tuple(dict.fromkeys(str(role) for role in roles if str(role).strip()))
    if not cleaned or len(cleaned) > MAX_GATE_ROLES:
        return None
    if mode == "single" and len(cleaned) != 1:
        return None
    if any(role not in PROJECT_ROLE_PERMISSIONS for role in cleaned):
        return None
    return mode, cleaned


def validate_review_policy(raw: object) -> list[str]:
    """Registry-level validation: a tool may only declare a lawful policy."""

    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["review_policy must be an object"]
    if normalize_policy(raw) is None:
        return [f"review_policy must be one of {MODES} with known project roles "
                f"(single requires exactly one role)"]
    return []


def resolve_gate_policy(*, gate_key: str | None, tool_policy: object = None) -> GatePolicy:
    """Resolve the policy for a gate: gate table first, then the tool, then the default."""

    key = str(gate_key or "").strip()
    if key and key in GATE_POLICY:
        normalized = normalize_policy(GATE_POLICY[key])
        if normalized is not None:
            return GatePolicy(mode=normalized[0], roles=normalized[1], source="gate_table")
    normalized = normalize_policy(tool_policy)
    if normalized is not None:
        return GatePolicy(mode=normalized[0], roles=normalized[1], source="tool_spec")
    return GatePolicy(mode=str(DEFAULT_POLICY["mode"]), roles=tuple(DEFAULT_POLICY["roles"]),
                      source="default")
