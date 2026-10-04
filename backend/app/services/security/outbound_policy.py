"""Single gateway for the AI outbound decision (W08).

Two paths used to decide independent of each other whether material may leave the host:

* the field-rerank path promoted catalog structure to ``confidential`` and required an explicit
  project authorization before it would send anything to a non-local provider;
* the prompt path only blocked ``restricted``/``confidential`` and let each caller declare its own
  levels.

Both now consult this module, so the classification floor, the outbound authorization list and the
send decision live in exactly one reviewed place. This is a *convergence* refactor: it deliberately
preserves the current strictness - it does not add allow-list entries, does not lower any
classification, and does not make either path more permissive. Unifying the *policy* itself (which
classification each kind of material should carry on the prompt path) is a bank-facing decision
that must be taken explicitly, not by this refactor.
"""
from __future__ import annotations

from typing import Any

LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

# An unknown or missing classification is treated as the most sensitive level rather than
# silently downgraded.
UNKNOWN_LEVEL = "restricted"

# Catalog structure (table/column names, comments, types) is treated as sensitive even when the
# project is only declared ``internal``: the floor is applied before anything may be sent out.
CATALOG_FLOOR = "confidential"


def normalize_level(declared: Any) -> str:
    return declared if declared in LEVELS else UNKNOWN_LEVEL


def outbound_authorized_project_ids(raw: str | None = None) -> set[str]:
    """Projects explicitly authorized for outbound model calls. The default configuration is empty."""

    if raw is None:
        from app.core.settings import get_settings

        raw = get_settings().ai_external_model_allowed_project_ids
    return {part.strip() for part in str(raw or "").split(",") if part.strip().isdigit()}


def catalog_confidentiality_floor(project: Any, *, authorized_ids: set[str] | None = None) -> str:
    """The classification floor for catalog-derived material.

    Explicitly authorized projects keep their declared level; everything else is raised to at
    least ``CATALOG_FLOOR``. Used by the rerank path (and available to any future catalog caller)
    so the rule cannot drift per call site.
    """

    declared = normalize_level(getattr(project, "confidentiality_level", None))
    ids = outbound_authorized_project_ids() if authorized_ids is None else authorized_ids
    if str(getattr(project, "id", "")) in ids:
        return declared
    return max((declared, CATALOG_FLOOR), key=LEVELS.__getitem__)


def ensure_external_send_allowed(level: str, local_only: bool) -> None:
    """Raise ``ValueError`` when material at ``level`` may not leave the host.

    ``local_only`` providers are always allowed. Non-local providers may carry only levels below
    ``confidential``; anything at or above the floor is denied.
    """

    normalized = level if level in LEVELS else UNKNOWN_LEVEL
    if normalized == "restricted" and not local_only:
        raise ValueError("restricted 内容只允许本地模型")
    if normalized == "confidential" and not local_only:
        raise ValueError("confidential 内容默认只允许 local_only 模型")


def external_send_denied(level: str, local_only: bool) -> str | None:
    """Non-raising variant returning the denial reason, for callers that classify rather than raise."""

    try:
        ensure_external_send_allowed(level, local_only)
    except ValueError as exc:
        return str(exc)
    return None
