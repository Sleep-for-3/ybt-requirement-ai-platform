"""Shared visibility policy for governed semantic rows.

The semantic read boundary deliberately has only three business-facing modes:
trusted facts, explicit review candidates, and audit-only history (the latter
is exposed only by callers that name an audit/history operation explicitly).
Keeping the status vocabulary here prevents graph, resolver, version, and
future ContextBuilder queries from drifting apart.
"""

from enum import Enum
from typing import Any


class SemanticVisibilityMode(str, Enum):
    TRUSTED = "trusted"
    CANDIDATE = "candidate"


_TRUSTED_STATUSES = ("confirmed",)
_CANDIDATE_STATUSES = ("confirmed", "draft", "ai_suggested")
_AUDIT_ONLY_STATUSES = ("rejected", "deprecated")


def _coerce_mode(mode: SemanticVisibilityMode | str) -> SemanticVisibilityMode:
    if isinstance(mode, SemanticVisibilityMode):
        return mode
    try:
        return SemanticVisibilityMode(str(mode))
    except ValueError as exc:
        raise ValueError(f"Unsupported semantic visibility mode: {mode}") from exc


def trusted_statuses() -> tuple[str, ...]:
    return _TRUSTED_STATUSES


def candidate_statuses() -> tuple[str, ...]:
    return _CANDIDATE_STATUSES


def audit_only_statuses() -> tuple[str, ...]:
    return _AUDIT_ONLY_STATUSES


def statuses_for(mode: SemanticVisibilityMode | str) -> tuple[str, ...]:
    return trusted_statuses() if _coerce_mode(mode) is SemanticVisibilityMode.TRUSTED else candidate_statuses()


def status_predicate(column: Any, mode: SemanticVisibilityMode | str):
    """Return a SQLAlchemy predicate for the explicit business visibility mode."""

    return column.in_(statuses_for(mode))


def is_visible(status: str, mode: SemanticVisibilityMode | str) -> bool:
    return str(status) in statuses_for(mode)


__all__ = [
    "SemanticVisibilityMode",
    "audit_only_statuses",
    "candidate_statuses",
    "is_visible",
    "status_predicate",
    "statuses_for",
    "trusted_statuses",
]
