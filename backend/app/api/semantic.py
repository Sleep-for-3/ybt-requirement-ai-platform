from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, SemanticBinding, SemanticConcept, SemanticRelation
from app.schemas.semantic import (
    SemanticBindingCreate,
    SemanticBindingRead,
    SemanticBindingUpdate,
    SemanticConceptCreate,
    SemanticConceptRead,
    SemanticConceptUpdate,
    SemanticGraphResponse,
    SemanticPathResponse,
    SemanticRelationCreate,
    SemanticRelationRead,
    SemanticRelationUpdate,
    SemanticResolveRequest,
    SemanticResolveResponse,
    SemanticStatusTransition,
)
from app.services.auth.dependencies import CurrentPrincipal, Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.semantic import (
    SemanticGraphService,
    SemanticResolver,
    apply_status_transition,
    get_project_entity,
    get_project_semantic_resource,
)


router = APIRouter(tags=["regulatory semantics"])


@router.post("/projects/{project_id}/semantic-concepts", response_model=SemanticConceptRead, status_code=201)
def create_concept(
    project_id: int,
    payload: SemanticConceptCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConcept:
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    values = payload.model_dump()
    values["concept_code"] = _normalize_code(values["concept_code"])
    concept = SemanticConcept(
        project_id=project_id,
        institution_id=project.institution_id,
        created_by=principal.username,
        **values,
    )
    db.add(concept)
    _flush_or_conflict(db, "Semantic concept code already exists in this project and type")
    _audit_create(db, principal, concept, "semantic_concept")
    db.commit()
    db.refresh(concept)
    return concept


@router.get("/projects/{project_id}/semantic-concepts", response_model=list[SemanticConceptRead])
def list_concepts(
    project_id: int,
    principal: CurrentPrincipal,
    concept_type: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[SemanticConcept]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    statement = select(SemanticConcept).where(SemanticConcept.project_id == project_id)
    if concept_type:
        statement = statement.where(SemanticConcept.concept_type == concept_type)
    if status:
        statement = statement.where(SemanticConcept.status == status)
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            SemanticConcept.concept_code.ilike(pattern) | SemanticConcept.concept_name.ilike(pattern)
        )
    return list(db.scalars(statement.order_by(SemanticConcept.id).limit(limit)).all())


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}", response_model=SemanticConceptRead)
def get_concept(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConcept:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)


@router.patch("/projects/{project_id}/semantic-concepts/{concept_id}", response_model=SemanticConceptRead)
def update_concept(
    project_id: int,
    concept_id: int,
    payload: SemanticConceptUpdate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConcept:
    PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    concept = get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
    _require_editable(concept)
    before = _snapshot(concept)
    values = payload.model_dump(exclude_unset=True)
    if "concept_code" in values:
        values["concept_code"] = _normalize_code(values["concept_code"])
    for key, value in values.items():
        setattr(concept, key, value)
    concept.version += 1
    _flush_or_conflict(db, "Semantic concept code already exists in this project and type")
    _audit_update(db, principal, concept, "semantic_concept", before)
    db.commit()
    db.refresh(concept)
    return concept


@router.post("/projects/{project_id}/semantic-concepts/{concept_id}/status", response_model=SemanticConceptRead)
def transition_concept(
    project_id: int,
    concept_id: int,
    payload: SemanticStatusTransition,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConcept:
    return _transition(db, principal, project_id, "semantic_concept", concept_id, payload)


@router.post("/projects/{project_id}/semantic-bindings", response_model=SemanticBindingRead, status_code=201)
def create_binding(
    project_id: int,
    payload: SemanticBindingCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticBinding:
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    get_project_semantic_resource(db, project_id, "semantic_concept", payload.semantic_concept_id)
    get_project_entity(db, project_id, payload.entity_type, payload.entity_id)
    binding = SemanticBinding(
        project_id=project_id,
        institution_id=project.institution_id,
        created_by=principal.username,
        **payload.model_dump(),
    )
    db.add(binding)
    _flush_or_conflict(db, "Semantic binding already exists")
    _audit_create(db, principal, binding, "semantic_binding")
    db.commit()
    db.refresh(binding)
    return binding


@router.get("/projects/{project_id}/semantic-bindings", response_model=list[SemanticBindingRead])
def list_bindings(
    project_id: int,
    principal: CurrentPrincipal,
    semantic_concept_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[SemanticBinding]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    statement = select(SemanticBinding).where(SemanticBinding.project_id == project_id)
    for column, value in (
        (SemanticBinding.semantic_concept_id, semantic_concept_id),
        (SemanticBinding.entity_type, entity_type),
        (SemanticBinding.entity_id, entity_id),
        (SemanticBinding.status, status),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return list(db.scalars(statement.order_by(SemanticBinding.id).limit(limit)).all())


@router.get("/projects/{project_id}/semantic-bindings/{binding_id}", response_model=SemanticBindingRead)
def get_binding(project_id: int, binding_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return get_project_semantic_resource(db, project_id, "semantic_binding", binding_id)


@router.patch("/projects/{project_id}/semantic-bindings/{binding_id}", response_model=SemanticBindingRead)
def update_binding(
    project_id: int,
    binding_id: int,
    payload: SemanticBindingUpdate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    binding = get_project_semantic_resource(db, project_id, "semantic_binding", binding_id)
    _require_editable(binding)
    before = _snapshot(binding)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(binding, key, value)
    _flush_or_conflict(db, "Semantic binding already exists")
    _audit_update(db, principal, binding, "semantic_binding", before)
    db.commit()
    db.refresh(binding)
    return binding


@router.post("/projects/{project_id}/semantic-bindings/{binding_id}/status", response_model=SemanticBindingRead)
def transition_binding(
    project_id: int,
    binding_id: int,
    payload: SemanticStatusTransition,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    return _transition(db, principal, project_id, "semantic_binding", binding_id, payload)


@router.post("/projects/{project_id}/semantic-relations", response_model=SemanticRelationRead, status_code=201)
def create_relation(
    project_id: int,
    payload: SemanticRelationCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticRelation:
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    if payload.source_concept_id == payload.target_concept_id:
        raise HTTPException(status_code=400, detail="Semantic self-relations are not allowed")
    get_project_semantic_resource(db, project_id, "semantic_concept", payload.source_concept_id)
    get_project_semantic_resource(db, project_id, "semantic_concept", payload.target_concept_id)
    relation = SemanticRelation(
        project_id=project_id,
        institution_id=project.institution_id,
        created_by=principal.username,
        **payload.model_dump(),
    )
    db.add(relation)
    _flush_or_conflict(db, "Semantic relation already exists")
    _audit_create(db, principal, relation, "semantic_relation")
    db.commit()
    db.refresh(relation)
    return relation


@router.get("/projects/{project_id}/semantic-relations", response_model=list[SemanticRelationRead])
def list_relations(
    project_id: int,
    principal: CurrentPrincipal,
    concept_id: int | None = None,
    relation_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[SemanticRelation]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    statement = select(SemanticRelation).where(SemanticRelation.project_id == project_id)
    if concept_id is not None:
        statement = statement.where(
            (SemanticRelation.source_concept_id == concept_id) | (SemanticRelation.target_concept_id == concept_id)
        )
    if relation_type:
        statement = statement.where(SemanticRelation.relation_type == relation_type)
    if status:
        statement = statement.where(SemanticRelation.status == status)
    return list(db.scalars(statement.order_by(SemanticRelation.id).limit(limit)).all())


@router.get("/projects/{project_id}/semantic-relations/{relation_id}", response_model=SemanticRelationRead)
def get_relation(project_id: int, relation_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return get_project_semantic_resource(db, project_id, "semantic_relation", relation_id)


@router.patch("/projects/{project_id}/semantic-relations/{relation_id}", response_model=SemanticRelationRead)
def update_relation(
    project_id: int,
    relation_id: int,
    payload: SemanticRelationUpdate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    relation = get_project_semantic_resource(db, project_id, "semantic_relation", relation_id)
    _require_editable(relation)
    before = _snapshot(relation)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(relation, key, value)
    _flush_or_conflict(db, "Semantic relation already exists")
    _audit_update(db, principal, relation, "semantic_relation", before)
    db.commit()
    db.refresh(relation)
    return relation


@router.post("/projects/{project_id}/semantic-relations/{relation_id}/status", response_model=SemanticRelationRead)
def transition_relation(
    project_id: int,
    relation_id: int,
    payload: SemanticStatusTransition,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
):
    return _transition(db, principal, project_id, "semantic_relation", relation_id, payload)


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}/neighbors", response_model=SemanticGraphResponse)
def concept_neighbors(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    direction: str = "both",
    max_depth: int = Query(default=1, ge=1, le=5),
    max_nodes: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    service = SemanticGraphService(db, project_id)
    depths, edges, truncated = service.traverse(
        concept_id, direction=direction, max_depth=max_depth, max_nodes=max_nodes
    )
    concepts = {item.id: item for item in service.concepts(set(depths))}
    return {
        "root_concept_id": concept_id,
        "nodes": [{"concept": concepts[item_id], "depth": depth} for item_id, depth in sorted(depths.items(), key=lambda pair: (pair[1], pair[0]))],
        "edges": [{"relation": relation, "direction": edge_direction} for relation, edge_direction in edges],
        "truncated": truncated,
    }


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}/upstream", response_model=SemanticGraphResponse)
def concept_upstream(project_id: int, concept_id: int, principal: CurrentPrincipal, max_depth: int = Query(default=5, ge=1, le=5), db: Session = Depends(get_db)):
    return concept_neighbors(project_id, concept_id, principal, "incoming", max_depth, 200, db)


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}/downstream", response_model=SemanticGraphResponse)
def concept_downstream(project_id: int, concept_id: int, principal: CurrentPrincipal, max_depth: int = Query(default=5, ge=1, le=5), db: Session = Depends(get_db)):
    return concept_neighbors(project_id, concept_id, principal, "outgoing", max_depth, 200, db)


@router.get("/projects/{project_id}/semantic-entities/{entity_type}/{entity_id}/concepts", response_model=list[SemanticConceptRead])
def entity_semantics(project_id: int, entity_type: str, entity_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    get_project_entity(db, project_id, entity_type, entity_id)
    return SemanticGraphService(db, project_id).entity_concepts(entity_type, entity_id)


@router.get("/projects/{project_id}/semantic-path", response_model=SemanticPathResponse)
def semantic_path(
    project_id: int,
    source_concept_id: int,
    target_concept_id: int,
    principal: CurrentPrincipal,
    direction: str = "outgoing",
    max_depth: int = Query(default=5, ge=1, le=5),
    db: Session = Depends(get_db),
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    concepts, relations = SemanticGraphService(db, project_id).shortest_path(
        source_concept_id, target_concept_id, direction=direction, max_depth=max_depth
    )
    return {
        "source_concept_id": source_concept_id,
        "target_concept_id": target_concept_id,
        "concept_ids": concepts,
        "relation_ids": relations,
        "found": bool(concepts),
    }


@router.post("/projects/{project_id}/semantic-resolve", response_model=SemanticResolveResponse)
def resolve_semantics(
    project_id: int,
    payload: SemanticResolveRequest,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return {"candidates": SemanticResolver(db, project_id).resolve(**payload.model_dump())}


def _transition(db: Session, principal: Principal, project_id: int, resource_type: str, resource_id: int, payload: SemanticStatusTransition):
    permissions = PermissionService(db, principal)
    permissions.require_project_permission(project_id, "project.view")
    allowed = {"task.manage", "business.review", "technical.review", "final.review"}
    if not (permissions.effective_project_permissions(project_id) & allowed):
        raise HTTPException(status_code=403, detail="Semantic status transition requires a review permission")
    project = db.get(Project, project_id)
    if payload.status == "confirmed" and project is not None and project.governance_workflow_enabled:
        raise HTTPException(status_code=409, detail="Semantic confirmation must be completed through semantic_governance_review")
    resource = get_project_semantic_resource(db, project_id, resource_type, resource_id)
    before = _snapshot(resource)
    apply_status_transition(resource, payload.status, principal.username)
    record_audit(
        db,
        action="semantic_status_transition",
        resource_type=resource_type,
        resource_id=resource.id,
        actor_user_id=principal.user_id,
        institution_id=resource.institution_id,
        project_id=resource.project_id,
        before=before,
        after={**_snapshot(resource), "comment": payload.comment},
    )
    db.commit()
    db.refresh(resource)
    return resource


def _normalize_code(value: str) -> str:
    return value.strip().upper()


def _require_editable(resource) -> None:
    if resource.status not in {"draft", "ai_suggested"}:
        raise HTTPException(status_code=409, detail="Confirmed, rejected, or deprecated semantic resources cannot be edited in place")


def _flush_or_conflict(db: Session, detail: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


def _snapshot(resource) -> dict:
    keys = [
        "id", "project_id", "concept_type", "concept_code", "concept_name", "semantic_concept_id",
        "entity_type", "entity_id", "binding_type", "source_concept_id", "relation_type",
        "target_concept_id", "status", "confidence_level", "confidence_score", "version", "source_type", "source_id",
        "definition", "description", "aliases_json", "business_domain", "owner_department",
        "confirmed_by", "confirmed_at",
    ]
    return {key: _audit_value(getattr(resource, key)) for key in keys if hasattr(resource, key)}


def _audit_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _audit_create(db: Session, principal: Principal, resource, resource_type: str) -> None:
    record_audit(
        db,
        action="semantic_create",
        resource_type=resource_type,
        resource_id=resource.id,
        actor_user_id=principal.user_id,
        institution_id=resource.institution_id,
        project_id=resource.project_id,
        after=_snapshot(resource),
    )


def _audit_update(db: Session, principal: Principal, resource, resource_type: str, before: dict) -> None:
    record_audit(
        db,
        action="semantic_update",
        resource_type=resource_type,
        resource_id=resource.id,
        actor_user_id=principal.user_id,
        institution_id=resource.institution_id,
        project_id=resource.project_id,
        before=before,
        after=_snapshot(resource),
    )
