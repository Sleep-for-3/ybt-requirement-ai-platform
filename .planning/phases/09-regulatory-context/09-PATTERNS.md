# Phase 9: Regulatory Context - Pattern Map

**Mapped:** 2026-08-20  
**Files analyzed:** 25 planned targets (the hardening tests may either extend test_semantic_layer.py or be split into test_semantic_hardening.py)  
**Analogs found:** 25 / 25 by exact, same-role, or same-data-flow match

The target list is derived from 09-CONTEXT.md decisions D-01 through D-24 and the four suggested plan boundaries in 09-RESEARCH.md. Names marked as [ASSUMED] in research are treated as planner-adjustable seams, not existing contracts.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| backend/app/models/semantic.py | model | CRUD / temporal read | backend/app/models/semantic.py current Concept + backend/app/models/deliverables.py version rows | exact role |
| backend/app/models/__init__.py | provider/export | import wiring | backend/app/models/__init__.py existing exports | exact |
| backend/app/schemas/semantic.py | schema | request-response / validation | same file Concept/Binding/Relation schemas | exact |
| backend/app/services/semantic/__init__.py | provider/export | import wiring | same file current service exports | exact |
| backend/app/services/semantic/binding_service.py | service/utility | CRUD / project lookup | same file ENTITY_MODELS and resource guards | exact role |
| backend/app/services/semantic/graph_service.py | service | graph traversal / request-response | same file project-scoped graph queries | exact role |
| backend/app/services/semantic/resolver.py | service | transform / deterministic ranking | same file resolver scoring loop | exact data flow |
| backend/app/services/semantic/status_policy.py | utility/policy | transform / query predicate | graph_service.py and binding_service.py status rules | role match |
| backend/app/services/semantic/entity_adapter.py | utility/adapter | transform / descriptor projection | binding_service.py allow-list + lineage resolver candidates | role match |
| backend/app/services/semantic/version_service.py | service | CRUD / temporal selection | governance workflow finalization + DeliverablePackageVersion | role and lifecycle match |
| backend/alembic/versions/202608200016_semantic_concept_versions.py | migration | batch data migration / schema | 202608200015_regulatory_semantic_layer.py | exact migration flow |
| backend/tests/test_semantic_layer.py | test | request-response / isolation | existing semantic CRUD, graph, governance and resolver tests | exact |
| backend/tests/test_semantic_migration.py | test | migration lifecycle / batch | existing semantic upgrade-downgrade tests | exact |
| backend/tests/test_semantic_hardening.py (optional split) | test | request-response / policy | test_semantic_layer.py | role match |
| backend/app/schemas/regulatory_context.py | schema | transform / request-response | backend/app/schemas/deliverables.py nested validators | role match |
| backend/app/services/semantic/context_authority.py | policy/utility | transform / ranking | project_readiness.service.py blockers + deliverables compiler claim types | role match |
| backend/app/services/semantic/context_builder.py | service | read-only projection / transform | project_readiness.service.py orchestration | role and flow match |
| backend/app/services/semantic/context_collectors.py | service | batch reads / joins / projection | deliverables.lineage_records.py and source_field_recommender.py | flow match |
| backend/app/services/semantic/context_conflicts.py | utility/service | transform / deterministic gaps | deliverables.validation_service.py and project_readiness.service.py | flow match |
| backend/tests/test_regulatory_context_contract.py | test | schema transform / serialization | test_semantic_layer.py API assertions + deliverables schema conventions | role match |
| backend/tests/test_regulatory_context_builder.py | test | batch integration / query-count | test_semantic_layer.py fixture + tests/conftest.py | flow match; query-count subpattern has no existing analog |
| backend/app/api/semantic.py | controller/router | request-response / CRUD | existing semantic router | exact |
| backend/app/api/regulatory_context.py | controller/router | request-response / read-only | semantic.py and projects.py project-scoped routes | role match |
| backend/app/main.py | config/router registration | request-response wiring | current include_router block | exact |
| backend/tests/test_regulatory_context_api.py | test | request-response / isolation | test_semantic_layer.py TestClient fixture | role and flow match |

Phase 10 generators and frontend routes are explicitly excluded. The mapping generator files may be cited below only as read-only analogs/anti-pattern evidence; they are not modification targets.

## Pattern Assignments

### backend/app/models/semantic.py (model, CRUD / temporal read)

**Analog:** current Concept/Binding/Relation declarations in backend/app/models/semantic.py, plus the existing version-row shape in backend/app/models/deliverables.py:216-236.

**Import and base pattern (semantic.py:1-6):**

~~~python
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin
~~~

**Stable identity constraint (semantic.py:9-18):**

~~~python
class SemanticConcept(Base, TimestampMixin):
    __tablename__ = "semantic_concepts"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "concept_type", "concept_code",
            name="uq_semantic_concept_project_type_code",
        ),
        Index("ix_semantic_concept_project_status", "project_id", "status"),
        Index("ix_semantic_concept_project_name", "project_id", "concept_name"),
    )
~~~

**Current projection fields (semantic.py:20-38):**

~~~python
id: Mapped[int] = mapped_column(Integer, primary_key=True)
institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
concept_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
concept_code: Mapped[str] = mapped_column(String(150), nullable=False)
concept_name: Mapped[str] = mapped_column(String(255), nullable=False)
definition: Mapped[str | None] = mapped_column(Text)
aliases_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
~~~

**Version-row analog (deliverables.py:216-236):** DeliverablePackageVersion uses a foreign key to its stable package, a non-null version_no, project_id, immutable snapshot fields, and UniqueConstraint(package_id, version_no). Copy the structural idea, not its file semantics.

**Assignment:** Add SemanticConceptVersion beside SemanticConcept. It must point to the stable Concept identity, use a unique pair (semantic_concept_id, version_no), a portable date-order check, and project/concept/status/effective-date indexes. Keep the Concept identity unique constraint exactly once; do not duplicate concept_type/code uniqueness on versions. Version rows own governed meaning, provenance, status, confirmation data and inclusive effective dates. Legacy Concept text remains a documented compatibility projection synchronized by the version service.

### backend/app/models/__init__.py (provider/export, import wiring)

**Analog (models/__init__.py:81-91 and 184-186):**

~~~python
from app.models.semantic import SemanticBinding, SemanticConcept, SemanticRelation

__all__ = [
    ...
    "SemanticBinding",
    "SemanticConcept",
    "SemanticRelation",
]
~~~

**Assignment:** Import and expose SemanticConceptVersion in the same two locations. Do not add a new model module solely for the version row unless the planner intentionally changes the model seam.

### backend/app/schemas/semantic.py (schema, request-response / validation)

**Import and literal pattern (semantic.py:1-18):**

~~~python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

ConceptType = Literal["business_term", "metric", "dimension", "code_set", "business_rule", "regulatory_rule"]
SemanticStatus = Literal["draft", "ai_suggested", "confirmed", "rejected", "deprecated"]
ConfidenceLevel = Literal["low", "medium", "high"]
~~~

**Strict input and normalization (semantic.py:25-59):**

~~~python
class SemanticConceptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_code: str = Field(min_length=1, max_length=150)
    aliases_json: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("concept_code")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped
~~~

**ORM read pattern (semantic.py:101-122):**

~~~python
class SemanticConceptRead(OrmModel):
    id: int
    project_id: int
    concept_code: str
    status: str
    version: int
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
~~~

**Assignment:** Add version create/update/read models with extra=forbid, bounded strings/lists, Literal lifecycle values and date validators. Additive Concept responses may expose current/latest effective version fields, but existing fields and endpoints remain. A confirmed version cannot be represented as an in-place PATCH payload; model the create/transition operation separately and reject invalid date intervals before the service transaction.

### backend/app/services/semantic/__init__.py (provider/export, import wiring)

**Analog (semantic/__init__.py:1-17):**

~~~python
from app.services.semantic.binding_service import (
    ENTITY_MODELS,
    apply_status_transition,
    get_project_entity,
    get_project_semantic_resource,
)
from app.services.semantic.graph_service import SemanticGraphService
from app.services.semantic.resolver import SemanticResolver
~~~

**Assignment:** Export the shared policy, adapter, version service and context services through deliberate names only. Preserve existing exports so Phase 8 imports remain valid; avoid importing the API router here.

### backend/app/services/semantic/binding_service.py (service/utility, CRUD / project lookup)

**Allow-list analog (binding_service.py:24-43):**

~~~python
ENTITY_MODELS = {
    "target_table": TargetTable,
    "target_field": TargetField,
    "mart_table": MartTable,
    "mart_field": MartField,
    "source_table": SourceTable,
    "source_field": SourceField,
    "scenario": ProductScenario,
    "knowledge_unit": KnowledgeUnit,
    "source_to_mart_mapping": SourceToMartMapping,
    "mart_to_ybt_mapping": MartToYbtMapping,
    "scenario_business_mapping": ScenarioBusinessMapping,
    "scenario_technical_lineage": ScenarioTechnicalLineage,
}
~~~

**Project guard (binding_service.py:53-62):**

~~~python
model = ENTITY_MODELS.get(entity_type)
if model is None:
    raise HTTPException(status_code=400, detail="Unsupported semantic binding entity_type")
entity = db.get(model, entity_id)
if entity is None:
    raise HTTPException(status_code=404, detail="Semantic binding target not found")
if int(getattr(entity, "project_id")) != project_id:
    raise HTTPException(status_code=400, detail="Semantic binding target belongs to another project")
return entity
~~~

**Lifecycle analog (binding_service.py:45-51, 82-95):** ALLOWED_TRANSITIONS is centralized in this service today; apply_status_transition rejects invalid transitions and records confirmed_by/confirmed_at on confirmation.

**Assignment:** Keep the 12-type allow-list as the source of truth but have entity_adapter own text extraction. Add only a version-specific binding foreign key if a concrete version-limited entity test requires it. Make binding status predicates delegate to status_policy; do not let this module grow a second status vocabulary.

### backend/app/services/semantic/graph_service.py (service, graph traversal / request-response)

**Existing traversal query (graph_service.py:15-50):**

~~~python
def traverse(..., statuses: tuple[str, ...] = ("confirmed", "draft", "ai_suggested")):
    rows = list(self.db.scalars(
        select(SemanticRelation).where(
            SemanticRelation.project_id == self.project_id,
            SemanticRelation.status.in_(statuses),
            or_(*clauses),
        ).order_by(SemanticRelation.id)
    ).all())
~~~

**Unsafe trusted-read predicates (graph_service.py:69-82 and 130-140):**

~~~python
SemanticBinding.status != "deprecated",
SemanticConcept.project_id == self.project_id,
SemanticConcept.status != "deprecated",
...
SemanticRelation.status != "deprecated",
~~~

**Assignment:** Preserve stable ordering, depth/node caps and project predicates, but replace default statuses and deprecated-only predicates with status_policy predicates. Trusted entity semantics, traversal, shortest path and Context-facing reads use confirmed only. Explicit candidate mode may add draft/ai_suggested; rejected/deprecated remain audit/history-only. Keep relations identity-level and non-temporal.

### backend/app/services/semantic/resolver.py (service, transform / deterministic ranking)

**Current ORM reflection to remove (resolver.py:23-36):**

~~~python
entity = get_project_entity(self.db, self.project_id, entity_type, entity_id)
code = self._first(query_code, getattr(entity, "field_code", None), getattr(entity, "table_code", None), getattr(entity, "scenario_code", None))
name = self._first(query_name, getattr(entity, "field_name", None), getattr(entity, "table_name", None), getattr(entity, "scenario_name", None), getattr(entity, "title", None))
description = self._first(
    comment,
    getattr(entity, "field_comment", None),
    getattr(entity, "description", None),
    getattr(entity, "field_definition", None),
    getattr(entity, "content", None),
)
concepts = list(self.db.scalars(select(SemanticConcept).where(
    SemanticConcept.project_id == self.project_id,
    SemanticConcept.status != "deprecated",
).order_by(SemanticConcept.id)).all())
~~~

**Candidate output and stable tie-break (resolver.py:44-57):**

~~~python
candidates.append({
    "semantic_concept_id": concept.id,
    "score": score,
    "match_reason": reason,
    "evidence": evidence,
    "status": "ai_suggested",
})
candidates.sort(key=lambda item: (-item["score"], item["semantic_concept_id"]))
return candidates[:limit]
~~~

**Current scoring order (resolver.py:59-77):** exact_code 1.0, exact_name 0.95, exact_alias 0.9, metadata_comment 0.75, then confirmed_historical_binding 0.7. This is evidence that must be repaired, not copied.

**Assignment:** Consume a descriptor from entity_adapter and policy-filtered concepts/versions. Rank confirmed binding first, then exact normalized code, canonical name, alias, regulatory text, and metadata/definition text. Use deterministic tier/reason/id tie-breaks. Every candidate keeps status ai_suggested, match_reason, bounded evidence and provenance; no resolver path auto-confirms or calls an LLM.

### backend/app/services/semantic/status_policy.py (utility/policy, transform / query predicate)

**Closest analog:** graph_service.py status filters above and binding_service.py ALLOWED_TRANSITIONS.

**Concrete seam to copy from research-grounded query shape (RESEARCH.md:400-424):**

~~~python
rows = select(SemanticRelation).where(
    SemanticRelation.project_id == project_id,
    policy.predicate(SemanticRelation.status, mode),
)
~~~

**Assignment:** Implement one small policy API (names may be adjusted): trusted_statuses() returns confirmed; candidate_statuses() returns confirmed, draft and ai_suggested; audit_only_statuses() returns rejected and deprecated; status_predicate(column, mode) creates SQL predicates. Apply it to Concept, Binding, Relation and Version reads. Callers must not pass ad-hoc status tuples. Rejected/deprecated may appear only in explicitly named audit/history queries.

### backend/app/services/semantic/entity_adapter.py (utility/adapter, transform / descriptor projection)

**Analog:** binding_service.py:24-37 is already an exact allow-list; lineage/resolver.py:20-48 is the closest candidate-producing adapter flow.

**Lineage candidate shape (lineage/resolver.py:20-48):**

~~~python
@dataclass(frozen=True)
class ResolutionResult:
    node: LineageNode
    candidates: tuple[LineageResolutionCandidate, ...]

def resolve_lineage_node(db: Session, node: LineageNode) -> ResolutionResult:
    candidate_groups = _candidate_groups(db, node)
    ...
    row = LineageResolutionCandidate(
        project_id=node.project_id,
        lineage_node_id=node.id,
        candidate_type=candidate_type,
        candidate_id=value.id,
        score=_score(node, value),
        match_reason=_match_reason(node),
        selected_flag=False,
    )
~~~

**Assignment:** Define a stable non-ORM descriptor containing entity_type, entity_id, project_id, code/name, aliases, semantic_text, bounded metadata and source references. Explicitly map all twelve allow-listed entities: TargetField regulatory_definition/original/refined/EAST/internal/remarks; Target/Mart/Source table and field comments/descriptions; ProductScenario description/owners; KnowledgeUnit content, target/source names, scope/confidentiality/document references; SourceToMart, MartToYbt, ScenarioBusiness and ScenarioTechnical fields for rules, open_questions, final/AI content, status/confidence/lineage. Enforce project ownership before building the descriptor. No expanding getattr chain and no new persistence model.

### backend/app/services/semantic/version_service.py (service, CRUD / temporal selection)

**Negative edit-counter analog (api/semantic.py:98-120):**

~~~python
concept = get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
_require_editable(concept)
...
concept.version += 1
...
db.commit()
db.refresh(concept)
~~~

**Governed immutable transition analog (governance/workflow.py:434-454):**

~~~python
target = db.get(model, target_id) if model is not None else None
if target is None:
    raise HTTPException(status_code=404, detail="Semantic workflow target not found")
if target.status not in {"draft", "ai_suggested"}:
    raise HTTPException(status_code=409, detail="Semantic target is not awaiting confirmation")
before_status = target.status
target.status = "confirmed"
target.confirmed_by = reviewed_by
target.confirmed_at = datetime.now(UTC)
record_audit(
    db,
    action="semantic_status_transition",
    resource_type=target_type,
    resource_id=target.id,
    institution_id=target.institution_id,
    project_id=target.project_id,
    before={"status": before_status},
    after={"status": "confirmed", "confirmed_by": reviewed_by, "workflow": "semantic_governance_review"},
)
~~~

**Assignment:** Own create/update/transition/effective selection and legacy projection sync. Select only confirmed rows where effective_from <= as_of and (effective_to is null or effective_to >= as_of); return zero/one row and raise a machine-readable temporal conflict when existing data yields multiple matches. Draft and ai_suggested rows may overlap as candidates. Reject confirmed in-place edits; changed meaning creates a new version. Enforce confirmed interval non-overlap in the write transaction for SQLite and PostgreSQL, normalize dates, and map conflicts to 409 without partial writes. Keep Binding/Relation identity-level.

### backend/alembic/versions/202608200016_semantic_concept_versions.py (migration, batch data migration / schema)

**Revision and SQLAlchemy operation pattern (202608200015:7-26):**

~~~python
import sqlalchemy as sa
from alembic import op

revision = "202608200015"
down_revision = "202607300014"

def upgrade() -> None:
    semantic_tables = {"semantic_concepts", "semantic_bindings", "semantic_relations"}
    existing = set()
    if not op.get_context().as_sql:
        inspector = sa.inspect(op.get_bind())
        existing = {table for table in semantic_tables if inspector.has_table(table)}
    if existing:
        if existing != semantic_tables:
            raise RuntimeError(f"Partial regulatory semantic schema detected: {sorted(existing)}")
        return
~~~

**Explicit table/index style (202608200015:27-57):** create tables with sa.Column, ForeignKey, UniqueConstraint and explicit op.create_index calls; do not import runtime model classes or Base.metadata into the new migration.

**Downgrade safety (202608200015:126-130):**

~~~python
def downgrade() -> None:
    inspector = sa.inspect(op.get_bind()) if not op.get_context().as_sql else None
    for table in ("semantic_relations", "semantic_bindings", "semantic_concepts"):
        if inspector is None or inspector.has_table(table):
            op.drop_table(table)
~~~

**Assignment:** Set down_revision to 202608200015. Create only semantic_concept_versions with FK, unique concept/version, date check and project/effective indexes. Read existing rows using the migration bind and insert exactly one bootstrap row per Concept with version_no=1, copying current meaning/status/source/confidence/confirmation data. The legacy version edit counter must not become historical version history. Use a documented deterministic effective date (created_at calendar date with fixed release fallback is the research recommendation). Make retries non-duplicating or fail loudly on partial schema. Downgrade drops only the new table/indexes; preserve concepts, bindings, relations, embedding_index_versions and all business data.

**Migration anti-pattern:** 202607140006 imports app.models at line 8; do not copy that into 016. test_semantic_migration.py:30-35 explicitly guards against Base.metadata and from app imports.

### backend/tests/test_semantic_layer.py (test, request-response / isolation)

**CRUD, normalization, isolation and compatibility version (test_semantic_layer.py:35-64):**

~~~python
created = _post(client, f"/api/projects/{project_a}/semantic-concepts", {
    "concept_code": " cust_no ",
    "concept_name": "客户统一编号",
    "aliases_json": ["统一客户号", "统一客户号", "  "],
})
assert created["concept_code"] == "CUST_NO"
hidden = client.get(f"/api/projects/{project_b}/semantic-concepts/{created['id']}")
assert hidden.status_code == 404
updated = client.patch(
    f"/api/projects/{project_a}/semantic-concepts/{created['id']}",
    json={"definition": "全行客户唯一标识", "confidence_level": "high"},
)
assert updated.status_code == 200
assert updated.json()["version"] == 2
~~~

**Allow-listed binding coverage (test_semantic_layer.py:67-103):** _required_binding_entities seeds target/mart/source/knowledge families and loops through every entity_type, asserting creation, duplicate 409, cross-project 400 and project-scoped listing. Extend this to descriptor coverage, not to new generator behavior.

**Governance and audit assertions (test_semantic_layer.py:159-198):** create ai_suggested, confirm through the route, assert confirmed_by/confirmed_at, reject locked PATCH/invalid transition, then query AuditLog and compare before/after status. Reuse this for version confirmation and immutable confirmed rows.

**Deterministic resolver assertions (test_semantic_layer.py:251-277):** call resolver twice, assert identical JSON, exact code is first and scores are descending. Add confirmed-binding-first, regulatory-text, evidence/provenance and rejected/deprecated tests.

**Fixture pattern (test_semantic_layer.py:354-378):**

~~~python
engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
Base.metadata.create_all(engine)
sessions = sessionmaker(bind=engine)
app.dependency_overrides[get_db] = override_get_db
try:
    with TestClient(app) as client:
        yield client, sessions
finally:
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
~~~

### backend/tests/test_semantic_migration.py (test, migration lifecycle / batch)

**Upgrade/downgrade round trip (test_semantic_migration.py:16-28):**

~~~python
database_path = tmp_path / "semantic-migration.db"
_run_alembic(database_path, "upgrade", "head")
_assert_semantic_schema(database_path)
_run_alembic(database_path, "downgrade", PREVIOUS_REVISION)
inspector = sa.inspect(sa.create_engine(f"sqlite:///{database_path.as_posix()}"))
assert "semantic_concepts" not in inspector.get_table_names()
assert "embedding_index_versions" in inspector.get_table_names()
_run_alembic(database_path, "upgrade", "head")
_assert_semantic_schema(database_path)
~~~

**Runtime-model-free migration guard (test_semantic_migration.py:30-35):**

~~~python
migration = (BACKEND_DIR / "alembic" / "versions" / f"{SEMANTIC_REVISION}_regulatory_semantic_layer.py").read_text(encoding="utf-8")
assert "Base.metadata" not in migration
assert "from app" not in migration
assert "drop_table(\"embedding_index_versions\")" not in migration
~~~

**Assignment:** Extend constants to 016 and add empty-to-head, 015-to-head, head-to-015-to-head and populated legacy Concept bootstrap cases. Inspect unique/check/index definitions and assert exactly one version row per pre-existing Concept, version_no=1 even when Concept.version > 1, and safe downgrade.

### backend/tests/test_semantic_hardening.py (optional split, test, request-response / policy)

**Analog:** test_semantic_layer.py status, graph, resolver and binding tests above.

**Assignment:** If the planner splits this file, keep it a focused policy/adapter/version suite: rejected and deprecated rows excluded from trusted entity semantics/graph/path/resolver; candidate mode admits only confirmed/draft/ai_suggested; all 12 descriptors expose real text; date boundaries are inclusive; overlap and confirmed PATCH rejection are atomic. Otherwise append those cases to test_semantic_layer.py and do not create this file.

### backend/app/schemas/regulatory_context.py (schema, transform / request-response)

**Nested strict-validation analog (schemas/deliverables.py:35-84):**

~~~python
class TemplateColumnMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_field: str = Field(min_length=1, max_length=100)
    excel_column: str = Field(min_length=1, max_length=3)

class TemplateSheetMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[TemplateColumnMappingInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rows(self) -> "TemplateSheetMappingInput":
        if self.header_row_end < self.header_row_start:
            raise ValueError("header_row_end must be greater than or equal to header_row_start")
        return self
~~~

**Bounded question input analog (schemas/deliverables.py:96-130):** PendingQuestionCreateRequest uses positive id bounds, Literal priority values and a stripped non-blank resolution validator. Use the same approach for bounded context target IDs, limits, dates and question/conflict codes.

**Assignment:** Create typed Scope, Target, Scenario, Semantic, Regulatory, Candidate, Mapping, Lineage, KnowledgeEvidence, Historical, Quality, Conflict, OpenQuestion and BuildMetadata sections. Define one ContextFact envelope with fact_type, bounded structured_value, authority, state, source_type/source_id, evidence references, version/effective period, observed_at and confidence. Set context_schema_version to 1.0, forbid extra fields, normalize as_of/reporting_period, and never expose ORM dumps or unconstrained JSON facts. Keep authority and lifecycle state as separate serialized fields.

### backend/app/services/semantic/context_authority.py (policy/utility, transform / ranking)

**Deterministic state/ranking analog (project_readiness/service.py:31-78):**

~~~python
@dataclass(frozen=True)
class DimensionSpec:
    completed: int
    required: int
    blockers: tuple[dict[str, str], ...]
    actions: tuple[str, ...]
    links: tuple[str, ...]

def build_project_readiness(db: Session, project_id: int) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        raise LookupError("Project not found")
    counts = _project_counts(db, project_id)
    dimensions = _dimension_specs(project_id, counts)
    rendered = {key: _render_dimension(spec) for key, spec in dimensions.items()}
~~~

**Evidence/claim distinction analog (deliverables/source_to_mart_compiler.py:14-20):**

~~~python
questions = [item.open_questions for item in business + technical if item.open_questions]
...
return {"mapping_id": mapping.id, "draft": content,
        "claim_type": "evidence_supported" if sources else "unverified",
        "open_questions": questions}
~~~

**Assignment:** Put the authority order in one code-defined map, separate from state: formal/human-confirmed and regulatory facts first, then confirmed semantic version, approved mapping, verified lineage, metadata, confirmed history, retrieved knowledge, and AI inference. Preserve source type and evidence even when authority is low. Retrieval similarity remains retrieved; AI candidates remain inferred/ai_suggested. Provide deterministic comparison helpers used by builder/conflicts and tests.

### backend/app/services/semantic/context_builder.py (service, read-only projection / transform)

**Orchestrator analog (project_readiness/service.py:41-78):** It validates project existence, gathers dimensions through a helper, renders stable output, computes critical blockers and returns a structured projection rather than ORM rows.

**Projection/aggregation analog (deliverables/lineage_records.py:26-82):**

~~~python
def build_lineage_records(db, project_id: int, target_table_id: int) -> list[dict]:
    table, fields = _target_scope(db, project_id, target_table_id)
    field_by_id = {field.id: field for field in fields}
    field_ids = set(field_by_id)
    if not field_ids:
        return []
    rows = db.execute(
        select(LineageEdge, source_node, target_node, ScriptFileVersion, ScriptFile)
        ...
        .where(
            LineageEdge.project_id == project_id,
            LineageEdge.enabled.is_(True),
            source_node.project_id == project_id,
            target_node.project_id == project_id,
        )
        .order_by(ScriptFile.relative_path, LineageEdge.id)
    ).all()
~~~

**Assignment:** Orchestrate only: normalize scope and as_of -> policy/version selection -> adapter descriptors -> collectors -> authority/state/provenance normalization -> explicit candidate ranking -> deterministic conflicts/questions -> RegulatoryContext serialization. It must not persist copied facts, mappings, lineage or snapshots and must not become a God Service. Validate target table/field/mart/scenario/concept belongs to requested project and let PermissionService validate caller visibility.

### backend/app/services/semantic/context_collectors.py (service, batch reads / joins / projection)

**Project-batched candidate analog (recommendation/source_field_recommender.py:29-91):**

~~~python
target = db.get(TargetField, target_field_id)
scenario = db.get(ProductScenario, scenario_id)
if target.project_id != scenario.project_id:
    raise ValueError("Scenario belongs to another project")
candidates = db.execute(
    select(SourceField, SourceTable, BusinessSystem, DataSource)
    .join(SourceTable, SourceTable.id == SourceField.source_table_id)
    .join(BusinessSystem, BusinessSystem.id == SourceTable.business_system_id)
    .outerjoin(DataSource, DataSource.id == SourceTable.datasource_id)
    .where(SourceField.project_id == target.project_id, BusinessSystem.enabled.is_(True))
).all()
...
scored.sort(key=lambda item: (item[0], -item[1].id), reverse=True)
~~~

**Mapping chain batching analog (deliverables/lineage_records.py:85-102):**

~~~python
mart_to_ybt = list(db.scalars(select(MartToYbtMapping).where(
    MartToYbtMapping.project_id == project_id,
    MartToYbtMapping.target_field_id.in_(field_ids),
)).all()) if field_ids else []
mart_field_ids = {mapping.mart_field_id for mapping in mart_to_ybt if mapping.mart_field_id}
source_to_mart = list(db.scalars(select(SourceToMartMapping).where(
    SourceToMartMapping.project_id == project_id,
    SourceToMartMapping.mart_field_id.in_(mart_field_ids),
)).all()) if mart_field_ids else []
~~~

**Evidence ordering analog (api/mapping_evidence.py:36-47):**

~~~python
select(MappingEvidenceReference)
    .where(
        MappingEvidenceReference.mapping_type == mapping_type,
        MappingEvidenceReference.mapping_id == mapping_id,
    )
    .order_by(MappingEvidenceReference.id)
~~~

**Historical matching analog (deliverables/historical.py:39-47):** Queries TargetField and ProductScenario with project_id predicates, chooses exact code/name matches, marks matched/ambiguous/unmatched, and retains source location/content_hash. Use its project-bounded matching and provenance, not its workbook parsing side effects.

**Lineage analog (deliverables/lineage_records.py:34-55):** One joined query constrains edge, source node, target node, script version and script to the same project and enabled/current versions, then sorts by relative path and edge id.

**Knowledge/retrieval analog (retrieval/hybrid_retriever.py:22-67, 205-257, 302-318):**

~~~python
visibility = or_(
    and_(KnowledgeUnit.knowledge_scope == "project", KnowledgeUnit.project_id == project_id),
    KnowledgeUnit.knowledge_scope == "global",
    and_(KnowledgeUnit.knowledge_scope == "institution", KnowledgeUnit.institution_name == project.bank_name),
)
predicates = [KnowledgeUnit.enabled.is_(True), visibility]
...
items = sorted(items, key=lambda item: (item["final_score"], -item["knowledge_unit_id"]), reverse=True)[:top_k]
...
return not scenario_id or unit.scenario_id in {None, scenario_id}
~~~

**Assignment:** Split collectors by concern (metadata/semantic, mappings, evidence, historical, lineage, knowledge) with bounded identifier sets. Every semantic/mapping/lineage query has project_id; validate institution ownership through PermissionService. Batch with IN, joins or select-in, rank in Python with explicit tier and stable ID/type tie-breakers, and cap only after ranking. Preserve KnowledgeUnit confidentiality, source location, content/document versions and RetrievalLog id. HybridRetriever currently commits a RetrievalLog; if used, treat that log as provenance and assert no authoritative fact mutation.

### backend/app/services/semantic/context_conflicts.py (utility/service, transform / deterministic gaps)

**Deterministic issue analog (deliverables/validation_service.py:12-44):**

~~~python
fields = list(db.scalars(select(TargetField).where(
    TargetField.project_id == package.project_id,
    TargetField.target_table_id == package.target_table_id,
).order_by(TargetField.id)).all())
...
if not business:
    issues.append(_issue("error", field.id, "business_mapping", "至少需要一个场景业务口径"))
...
if item.lineage_status == "stale":
    issues.append(_issue("warning", field.id, "stale_lineage", "技术溯源引用的脚本血缘已过期"))
...
if not source_mappings:
    issues.append(_issue("error", field.id, "source_to_mart_mapping", "缺少业务系统到监管集市口径"))
~~~

**Stable issue envelope (validation_service.py:49-72):**

~~~python
result = {
    "error_count": sum(item["severity"] == "error" for item in issues),
    "warning_count": sum(item["severity"] == "warning" for item in issues),
    "issues": issues,
}

def _issue(severity, field_id, code, message):
    return {"severity": severity, "target_field_id": field_id, "code": code, "message": message}
~~~

**Assignment:** Generate typed conflicts and open questions without writing PendingQuestion rows. Emit stable codes for missing confirmed binding/version, MISSING_SOURCE_MAPPING, missing Mart-to-YBT, missing/stale lineage, missing evidence, historical-only definition and contradictory authoritative facts. Sort by code, target identity and source IDs; never silently choose a winner. Reuse PendingQuestion model/schema only as vocabulary/context, not as a persistence side effect of a read-only build.

### backend/tests/test_regulatory_context_contract.py (test, schema transform / serialization)

**Analog:** semantic schema tests in test_semantic_layer.py assert normalized API JSON; deliverables schema validators use extra=forbid and model/field validators.

**Assignment:** Assert context_schema_version is exactly 1.0, all sections serialize deterministically, ContextFact carries authority separately from state, structured values reject unconstrained/extra fields, inclusive dates and bounded IDs/limits validate, retrieval cannot serialize as confirmed, provenance includes source/evidence/version/retrieval/confidentiality fields, and ORM objects are not accepted as whole dumps.

### backend/tests/test_regulatory_context_builder.py (test, batch integration / query-count)

**Fixture analog:** test_semantic_layer.py:354-378 uses an in-memory SQLite StaticPool, Base.metadata.create_all, dependency override and cleanup; tests/conftest.py:21-31 supplies a minimal db_session fixture.

**Projection assertions to copy:** seed two institutions/projects like test_semantic_layer.py:286-296, reuse _required_binding_entities at lines 313-351, and assert cross-project reads are absent. Seed acceptance target 2.3 同业客户表 / 客户统一编号 with effective v1/v2, mappings, evidence, KnowledgeUnit and lineage.

**Required query-count pattern:** no existing backend test currently uses before_cursor_execute/event.listen. Add a local SQLAlchemy event listener around the builder call, count cursor executions, remove the listener in finally, and assert a measured bounded count after batching. Also assert no per-row db.get() loop, no copied context table, stable repeated output, deterministic conflicts/questions and unchanged authoritative row counts/status/timestamps. Do not guess the threshold before measuring the representative fixture.

### backend/app/api/semantic.py (controller/router, request-response / CRUD)

**Imports and security pattern (api/semantic.py:1-36):**

~~~python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Project, SemanticBinding, SemanticConcept, SemanticRelation
from app.services.auth.dependencies import CurrentPrincipal, Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
~~~

**Project-scoped CRUD (api/semantic.py:39-60, 63-84):**

~~~python
project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
...
db.add(concept)
_flush_or_conflict(db, "Semantic concept code already exists in this project and type")
_audit_create(db, principal, concept, "semantic_concept")
db.commit()
db.refresh(concept)
return concept
~~~

**Resolver endpoint (api/semantic.py:371-379):**

~~~python
@router.post("/projects/{project_id}/semantic-resolve", response_model=SemanticResolveResponse)
def resolve_semantics(...):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return {"candidates": SemanticResolver(db, project_id).resolve(**payload.model_dump())}
~~~

**Integrity/error and audit patterns (api/semantic.py:382-424, 442-466):** status transitions require review permission, use apply_status_transition, record_audit, commit/refresh; _flush_or_conflict catches IntegrityError, rolls back and raises HTTP 409.

**Assignment:** Keep all Phase 8 Concept/Binding/Relation routes and response fields. Add version/current-effective routes additively, route temporal conflicts to 409 and validation to 400/422, and ensure direct confirmed Concept PATCH becomes a version operation or explicit compatibility error. Do not add Context building to any mutating route.

### backend/app/api/regulatory_context.py (controller/router, request-response / read-only)

**Closest project route analog:** semantic.py:63-84 and projects.py:41-43 use a project path, CurrentPrincipal, db dependency, PermissionService project.view and typed response models.

**Permission pattern (auth/permission_service.py:94-98):**

~~~python
def require_project_permission(self, project_id: int, permission: str) -> Project:
    project = self._visible_project(project_id)
    if permission not in self._permissions_for_project(project):
        raise HTTPException(status_code=403, detail=f"Missing project permission: {permission}")
    return project
~~~

**Assignment:** Create a router with an additive read-only/debug context build endpoint under the existing project-aware style. Accept project plus optional target table/field, scenario, mart field, semantic concept, as_of, reporting_period and candidate mode through the typed Pydantic request. Require project.view before calling ContextBuilder; validate all target IDs against that project; return RegulatoryContext; never commit authoritative facts or expose ORM rows. The exact HTTP verb/path is discretionary but must remain additive and project-scoped.

### backend/app/main.py (config/router registration, request-response wiring)

**Router import block (main.py:11-55):**

~~~python
from app.api import (
    ...
    semantic,
)
~~~

**Secured registration (main.py:136-182):**

~~~python
secured = [Depends(guard_project_resource)]
...
app.include_router(semantic.router, prefix=settings.api_prefix, dependencies=secured)
~~~

**Assignment:** Import regulatory_context beside semantic and include it with settings.api_prefix and the same secured dependency list. Preserve existing router ordering and exception handlers. No frontend registration belongs in Phase 9.

### backend/tests/test_regulatory_context_api.py (test, request-response / isolation)

**Analog:** test_semantic_layer.py TestClient context manager and project isolation assertions at lines 35-64, 286-296 and 354-378.

**Assignment:** Verify project.view authorization and two-project/two-institution isolation, target ID ownership, stable response serialization, as_of v1/v2 selection, candidate mode semantics, missing mapping/lineage/evidence conflicts, no authoritative mutations, provenance/confidentiality propagation, and compatibility of existing semantic endpoints. Add API tests for 409 temporal conflicts and 422 schema validation.

## Shared Patterns

### Project and institution isolation

**Sources:** auth/permission_service.py:46-98, 147-175; semantic/binding_service.py:53-62; retrieval/hybrid_retriever.py:37-52, 302-318.

Every controller first calls PermissionService.require_project_permission. Every collector adds project_id predicates. Semantic/mapping/lineage rows are project-local. Knowledge visibility may include global/institution rows only through HybridRetriever's established scope predicate. Never accept a client institution_id override or treat free-text institution_name as ownership.

### Governance, human confirmation and AuditLog

**Sources:** governance/audit.py:15-72; governance/workflow.py:434-454; api/semantic.py:382-407.

~~~python
record_audit(
    db,
    action="semantic_status_transition",
    resource_type=target_type,
    resource_id=target.id,
    institution_id=target.institution_id,
    project_id=target.project_id,
    before={"status": before_status},
    after={"status": "confirmed", "confirmed_by": reviewed_by, "workflow": "semantic_governance_review"},
)
~~~

Use record_audit with redacted summaries for version lifecycle changes and any authoritative transition. Resolver candidates and retrieved context facts never call confirmation or write status.

### Pydantic strictness and bounded output

**Sources:** schemas/semantic.py:21-59, 101-122, 238-257; schemas/deliverables.py:35-84.

Use ConfigDict(extra="forbid"), Literal vocabularies, Field min/max/ge/le constraints, strip/normalize validators and model validators for cross-field date/section invariants. Context sections are typed projections; do not return whole ORM model dictionaries or an unconstrained dict[str, Any] fact store.

### Deterministic ranking and ordering

**Sources:** semantic/resolver.py:44-57; retrieval/hybrid_retriever.py:228-232; recommendation/source_field_recommender.py:83-91; deliverables/lineage_records.py:54-55.

Rank with explicit tiers and stable secondary keys (entity type/id, concept id, mapping id, evidence id). Apply limits only after ranking. Database natural order plus limit(50) is not a ContextBuilder strategy; source_to_mart_generator.py:98-110 is a read-only anti-pattern example, not a target file.

### Batched collectors and provenance

**Sources:** deliverables/lineage_records.py:34-55, 85-102; recommendation/source_field_recommender.py:39-91; hybrid_retriever.py:205-257.

Collect IDs first, then use IN, joins or select-in. Return typed fact candidates with source type/id, evidence IDs, effective/version data, observed time, project/institution and knowledge confidentiality/source locations. Do not call db.get once per row. If HybridRetriever is used, carry RetrievalLog id and preserve its confidentiality/source metadata; its existing log commit is the only expected retrieval provenance side effect and must be tested explicitly.

### Deterministic conflicts and open questions

**Sources:** deliverables/validation_service.py:12-72; project_readiness/service.py:191-213; models/deliverables.py:135-155.

Use machine-readable code/severity/target identity/message envelopes and stable sorting. ContextBuilder returns in-memory ContextConflict/OpenQuestion values and does not persist PendingQuestion. Missing, stale, contradictory and evidence-insufficient states must be visible rather than silently inferred.

### Read-only projection boundary

**Sources:** project_readiness/service.py:41-78; deliverables/lineage_records.py:26-82.

ContextBuilder may read existing Metadata, Mapping, Knowledge, Evidence, HistoricalCaliber, Lineage and version rows, but it creates no context fact, mapping, lineage or cache/snapshot table. API build calls do not change authoritative status, timestamps or content. Phase 10 SQL generators, generator routes, frontend routes, graph infrastructure and product multi-agent features remain out of scope.

## No Analog Found

| Planned subpattern | Role / Data Flow | Why no close analog exists | Planner direction |
|---|---|---|---|
| before_cursor_execute query-count instrumentation in test_regulatory_context_builder.py | test utility / batch performance | No backend test currently imports SQLAlchemy event or counts cursor executions | Add a local listener with finally cleanup; measure the acceptance fixture before locking a threshold. |
| One authority-rank module separate from lifecycle state | policy / transform | Existing code has confidence_level, claim_type and readiness blockers but no shared authority enum/rank | Use context_authority.py as the single map; retain source type, state, confidence and provenance separately. |
| One context conflict/question catalog | utility / transform | Existing validation/readiness issue codes are close but no RegulatoryContext contract exists | Use context_conflicts.py with stable codes including exact MISSING_SOURCE_MAPPING; do not persist PendingQuestion rows. |
| Inclusive effective-date semantic version selection with overlap rejection | service / CRUD | Existing version tables are snapshots/counters and no service handles date-effective semantic truth | Use version_service.py plus the portable model constraints and transactional overlap check described above. |

## Metadata

**Analog search scope:** backend/app/models, backend/app/schemas, backend/app/services/semantic, backend/app/services/auth, backend/app/services/governance, backend/app/services/retrieval, backend/app/services/mapping, backend/app/services/deliverables, backend/app/services/lineage, backend/app/api, backend/tests, backend/alembic/versions, and Phase 9 CONTEXT/RESEARCH.  
**Files scanned:** 25 planned targets plus 30+ analog files/ranges.  
**Important exclusions:** backend/app/services/mapping/*generator.py and all frontend files are analog evidence only, never Phase 9 modification targets.  
**Pattern extraction date:** 2026-08-20.

## PATTERN MAPPING COMPLETE
