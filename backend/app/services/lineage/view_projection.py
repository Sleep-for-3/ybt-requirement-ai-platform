"""View-specific projections for lineage graph and path responses.

The platform stores one governed set of lineage facts.  ``business`` and
``technical`` are *presentation contracts* over those facts, not two
independent graphs:

* ``business`` keeps the governed Chinese business name as the primary label
  and exposes the physical identifier as the secondary label.
* ``technical`` promotes the physical/qualified identifier to the primary
  label and keeps the business name as supporting context.

The projection never invents a label.  When a technical identifier is not
available the technical view falls back to the existing business label and
records ``primary_source="business_fallback"`` so reviewers can see that the
technical identifier is missing instead of silently reading a business name
as if it were a physical column.
"""

from __future__ import annotations

from typing import Any

BUSINESS = "business"
TECHNICAL = "technical"
SUPPORTED_VIEWS = (BUSINESS, TECHNICAL)


def validate_view(view: str) -> str:
    normalized = str(view or "").strip().lower()
    if normalized not in SUPPORTED_VIEWS:
        raise ValueError("Invalid lineage view")
    return normalized


def project_display(display: dict[str, Any], view: str) -> dict[str, Any]:
    """Return the display DTO projected for one view without mutating the input."""

    normalized = validate_view(view)
    projected = dict(display or {})
    if "business_display_name" in projected:
        # Already projected once; reuse the frozen source labels so repeated
        # projection (for example graph node reuse across two responses) is
        # idempotent and cannot promote a technical label to a business label.
        business_label = projected.get("business_display_name")
        technical_label = projected.get("technical_display_name")
    else:
        business_label = (
            projected.get("display_name")
            or projected.get("business_name")
            or projected.get("comment")
            or projected.get("technical_name")
        )
        technical_label = (
            projected.get("technical_identifier")
            or projected.get("qualified_technical_name")
            or projected.get("technical_name")
        )
    if normalized == BUSINESS:
        primary = business_label or technical_label
        primary_source = projected.get("display_name_source") or "missing"
        if primary and not projected.get("display_name"):
            primary_source = "technical_name"
        secondary = technical_label if technical_label and technical_label != primary else None
    else:
        primary = technical_label or business_label
        primary_source = "technical_identifier" if technical_label else "business_fallback"
        secondary = business_label if business_label and business_label != primary else None

    projected["view"] = normalized
    projected["business_display_name"] = business_label
    projected["technical_display_name"] = technical_label
    projected["display_name"] = primary or "缺少业务备注"
    projected["display_name_source"] = primary_source
    projected["view_secondary_label"] = secondary
    return projected


def project_node(node: dict[str, Any], view: str) -> dict[str, Any]:
    """Project one lineage node in place and return it for chaining."""

    normalized = validate_view(view)
    display = project_display(node.get("display") or {}, normalized)
    node["display"] = display
    node["view"] = normalized
    node["projection"] = {
        "view": normalized,
        "primary": display["display_name"],
        "primary_source": display["display_name_source"],
        "secondary": display.get("view_secondary_label"),
        "label_quality": display.get("label_quality"),
    }
    return node


def project_nodes(nodes: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
    for node in nodes:
        project_node(node, view)
    return nodes


__all__ = [
    "BUSINESS",
    "SUPPORTED_VIEWS",
    "TECHNICAL",
    "project_display",
    "project_node",
    "project_nodes",
    "validate_view",
]
