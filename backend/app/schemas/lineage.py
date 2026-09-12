from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


LineageRootType = Literal[
    "target_field",
    "mart_field",
    "source_field",
    "catalog_column",
    "lineage_node",
]
LineageDirection = Literal["upstream", "downstream", "both"]
LineageView = Literal["business", "technical"]


class LineageNodeProjection(BaseModel):
    """One view's primary/secondary label contract for a graph node."""

    view: LineageView
    primary: str
    primary_source: str
    secondary: str | None = None
    label_quality: str | None = None


class LineagePathNode(BaseModel):
    id: str
    entity_type: str
    canonical_entity_id: int | None = None
    node_type: str
    display: dict[str, Any]
    view: LineageView | None = None
    projection: LineageNodeProjection | None = None
    current_display: dict[str, Any] | None = None
    layer_code: str
    layer_name: str
    technical_identifier: str | None = None
    unresolved_flag: bool = False
    resolution_status: str
    lineage_node_ids: list[int] = Field(default_factory=list)
    revision_node_keys: list[str] = Field(default_factory=list)
    script_file_version_ids: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LineagePathEdge(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    relation_source: str
    mapping_type: str | None = None
    mapping_id: int | None = None
    transformation_type: str | None = None
    transformation_expression: str | None = None
    join_condition: str | None = None
    filter_condition: str | None = None
    aggregation_rule: str | None = None
    code_mapping_rule: str | None = None
    source_line_start: int | None = None
    source_line_end: int | None = None
    confidence_level: str
    verification_status: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)


class LineageResolvedPath(BaseModel):
    path_id: str
    root_node_id: str
    terminal_node_id: str
    direction: LineageDirection
    node_ids: list[str]
    edge_ids: list[str]
    traversal_steps: list[dict[str, Any]] = Field(default_factory=list)
    data_flow_node_ids: list[str]
    complete: bool
    confidence: str
    unresolved_node_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class LineageGapRecommendation(BaseModel):
    gap_type: str
    problem_statement: str
    recommended_change: str
    alternative_options: list[str] = Field(default_factory=list)
    rationale: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    affected_assets: list[str] = Field(default_factory=list)
    estimated_impact: str
    confidence_level: str
    approval_status: str = "pending_review"


class LineagePathResponse(BaseModel):
    project_id: int
    root: dict[str, Any]
    revision_id: int | None
    revision_no: int | None
    as_of: datetime | None
    direction: LineageDirection
    depth: int = Field(ge=1, le=10)
    view: LineageView
    nodes: list[LineagePathNode]
    edges: list[LineagePathEdge]
    paths: list[LineageResolvedPath]
    unresolved_nodes: list[LineagePathNode]
    gap_recommendations: list[LineageGapRecommendation]
    truncated: bool
    warnings: list[str] = Field(default_factory=list)
    confidence: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class RepositoryMonitorUpdateRequest(BaseModel):
    enabled: bool
    poll_interval_minutes: int = Field(default=60, ge=5, le=10_080)
    run_immediately: bool = False


__all__ = [
    "LineageDirection",
    "LineageGapRecommendation",
    "LineageNodeProjection",
    "LineagePathEdge",
    "LineagePathNode",
    "LineagePathResponse",
    "LineageResolvedPath",
    "LineageRootType",
    "LineageView",
    "RepositoryMonitorUpdateRequest",
]
