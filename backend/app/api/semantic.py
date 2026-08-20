from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, SemanticBinding, SemanticConcept, SemanticConceptVersion, SemanticRelation
from app.schemas.semantic import (
    SemanticBindingCreate,
    SemanticBindingRead,
    SemanticBindingUpdate,
    SemanticConceptCreate,
    SemanticConceptRead,
    SemanticConceptUpdate,
    SemanticConceptVersionCreate,
    SemanticConceptVersionRead,
    SemanticConceptVersionStatusTransition,
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
    SemanticVisibilityMode,
    apply_status_transition,
    create_concept_version,
    create_concept_with_initial_version,
    get_project_entity,
    get_project_semantic_resource,
    patch_concept_via_version_service,
    resolve_effective_version,
    transition_concept_status,
    transition_version_status,
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
    concept = create_concept_with_initial_version(
        db,
        project_id=project_id,
        institution_id=project.institution_id,
        created_by=principal.username,
        values=values,
    )
    _audit_create(db, principal, concept, "semantic_concept")
    db.commit()
    db.refresh(concept)
    return _attach_version_projection(db, concept)


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
    concepts = list(db.scalars(statement.order_by(SemanticConcept.id).limit(limit)).all())
    return [_attach_version_projection(db, concept) for concept in concepts]


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}", response_model=SemanticConceptRead)
def get_concept(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConcept:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return _attach_version_projection(
        db, get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
    )


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
    before = _snapshot(concept)
    values = payload.model_dump(exclude_unset=True)
    if "concept_code" in values:
        values["concept_code"] = _normalize_code(values["concept_code"])
    concept = patch_concept_via_version_service(
        db, project_id=project_id, concept_id=concept_id, values=values,
    )
    _audit_update(db, principal, concept, "semantic_concept", before)
    db.commit()
    db.refresh(concept)
    return _attach_version_projection(db, concept)


@router.post("/projects/{project_id}/semantic-concepts/{concept_id}/status", response_model=SemanticConceptRead)
def transition_concept(
    project_id: int,
    concept_id: int,
    payload: SemanticStatusTransition,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConcept:
    return _transition(db, principal, project_id, "semantic_concept", concept_id, payload)


@router.get(
    "/projects/{project_id}/semantic-concepts/{concept_id}/versions",
    response_model=list[SemanticConceptVersionRead],
)
def list_concept_versions(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[SemanticConceptVersion]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
    statement = select(SemanticConceptVersion).where(
        SemanticConceptVersion.project_id == project_id,
        SemanticConceptVersion.semantic_concept_id == concept_id,
    )
    if status:
        statement = statement.where(SemanticConceptVersion.status == status)
    return list(db.scalars(statement.order_by(SemanticConceptVersion.version_no).limit(limit)).all())


@router.post(
    "/projects/{project_id}/semantic-concepts/{concept_id}/versions",
    response_model=SemanticConceptVersionRead,
    status_code=201,
)
def create_version(
    project_id: int,
    concept_id: int,
    payload: SemanticConceptVersionCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConceptVersion:
    project = PermissionService(db, principal).require_project_permission(project_id, "business.edit")
    concept = get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
    values = payload.model_dump(exclude_none=True)
    version = create_concept_version(
        db,
        concept=concept,
        project_id=project_id,
        values=values,
        created_by=principal.username,
        effective_from=values.pop("effective_from", None),
        effective_to=values.pop("effective_to", None),
        status=values.get("status"),
    )
    _audit_create(db, principal, version, "semantic_concept_version")
    db.commit()
    db.refresh(version)
    return version


@router.get(
    "/projects/{project_id}/semantic-concepts/{concept_id}/versions/effective",
    response_model=SemanticConceptVersionRead | None,
)
def get_effective_version(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SemanticConceptVersion | None:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
    return resolve_effective_version(db, concept_id, as_of or date.today(), project_id=project_id)


@router.get(
    "/projects/{project_id}/semantic-concepts/{concept_id}/versions/{version_id}",
    response_model=SemanticConceptVersionRead,
)
def get_concept_version(
    project_id: int,
    concept_id: int,
    version_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConceptVersion:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    version = db.get(SemanticConceptVersion, version_id)
    if version is None or version.project_id != project_id or version.semantic_concept_id != concept_id:
        raise HTTPException(status_code=404, detail="SemanticConceptVersion not found")
    return version


@router.post(
    "/projects/{project_id}/semantic-concepts/{concept_id}/versions/{version_id}/status",
    response_model=SemanticConceptVersionRead,
)
def transition_version(
    project_id: int,
    concept_id: int,
    version_id: int,
    payload: SemanticConceptVersionStatusTransition,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> SemanticConceptVersion:
    permissions = PermissionService(db, principal)
    permissions.require_project_permission(project_id, "project.view")
    allowed = {"task.manage", "business.review", "technical.review", "final.review"}
    if not (permissions.effective_project_permissions(project_id) & allowed):
        raise HTTPException(status_code=403, detail="Semantic status transition requires a review permission")
    project = db.get(Project, project_id)
    if payload.status == "confirmed" and project is not None and project.governance_workflow_enabled:
        raise HTTPException(status_code=409, detail="Semantic confirmation must be completed through semantic_governance_review")
    version = db.get(SemanticConceptVersion, version_id)
    if version is None or version.project_id != project_id or version.semantic_concept_id != concept_id:
        raise HTTPException(status_code=404, detail="SemanticConceptVersion not found")
    before = _snapshot(version)
    version = transition_version_status(
        db, version, payload.status, principal.username, project_id=project_id,
    )
    record_audit(
        db,
        action="semantic_status_transition",
        resource_type="semantic_concept_version",
        resource_id=version.id,
        actor_user_id=principal.user_id,
        institution_id=version.institution_id,
        project_id=version.project_id,
        before=before,
        after={**_snapshot(version), "comment": payload.comment},
    )
    db.commit()
    db.refresh(version)
    return version


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
    mode: SemanticVisibilityMode = SemanticVisibilityMode.TRUSTED,
    max_depth: int = Query(default=1, ge=1, le=5),
    max_nodes: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    service = SemanticGraphService(db, project_id)
    depths, edges, truncated = service.traverse(
        concept_id, direction=direction, max_depth=max_depth, max_nodes=max_nodes, mode=mode,
    )
    concepts = {item.id: item for item in service.concepts(set(depths), mode=mode)}
    return {
        "root_concept_id": concept_id,
        "nodes": [{"concept": concepts[item_id], "depth": depth} for item_id, depth in sorted(depths.items(), key=lambda pair: (pair[1], pair[0]))],
        "edges": [{"relation": relation, "direction": edge_direction} for relation, edge_direction in edges],
        "truncated": truncated,
    }


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}/upstream", response_model=SemanticGraphResponse)
def concept_upstream(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    mode: SemanticVisibilityMode = SemanticVisibilityMode.TRUSTED,
    max_depth: int = Query(default=5, ge=1, le=5),
    db: Session = Depends(get_db),
):
    return concept_neighbors(
        project_id, concept_id, principal, direction="incoming", mode=mode, max_depth=max_depth, max_nodes=200, db=db,
    )


@router.get("/projects/{project_id}/semantic-concepts/{concept_id}/downstream", response_model=SemanticGraphResponse)
def concept_downstream(
    project_id: int,
    concept_id: int,
    principal: CurrentPrincipal,
    mode: SemanticVisibilityMode = SemanticVisibilityMode.TRUSTED,
    max_depth: int = Query(default=5, ge=1, le=5),
    db: Session = Depends(get_db),
):
    return concept_neighbors(
        project_id, concept_id, principal, direction="outgoing", mode=mode, max_depth=max_depth, max_nodes=200, db=db,
    )


@router.get("/projects/{project_id}/semantic-entities/{entity_type}/{entity_id}/concepts", response_model=list[SemanticConceptRead])
def entity_semantics(
    project_id: int,
    entity_type: str,
    entity_id: int,
    principal: CurrentPrincipal,
    mode: SemanticVisibilityMode = SemanticVisibilityMode.TRUSTED,
    db: Session = Depends(get_db),
):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    get_project_entity(db, project_id, entity_type, entity_id)
    return SemanticGraphService(db, project_id).entity_concepts(entity_type, entity_id, mode=mode)


@router.get("/projects/{project_id}/semantic-path", response_model=SemanticPathResponse)
def semantic_path(
    project_id: int,
    source_concept_id: int,
    target_concept_id: int,
    principal: CurrentPrincipal,
    direction: str = "outgoing",
    mode: SemanticVisibilityMode = SemanticVisibilityMode.TRUSTED,
    max_depth: int = Query(default=5, ge=1, le=5),
    db: Session = Depends(get_db),
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    concepts, relations = SemanticGraphService(db, project_id).shortest_path(
        source_concept_id, target_concept_id, direction=direction, max_depth=max_depth, mode=mode,
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
    if resource_type == "semantic_concept":
        resource = transition_concept_status(
            db,
            project_id=project_id,
            concept_id=resource_id,
            new_status=payload.status,
            actor=principal.username,
        )
    else:
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
    return _attach_version_projection(db, resource) if resource_type == "semantic_concept" else resource


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
        "confirmed_by", "confirmed_at", "version_no", "semantic_concept_id", "provenance_json",
        "effective_from", "effective_to",
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


def _attach_version_projection(db: Session, concept: SemanticConcept) -> SemanticConcept:
    """Expose canonical version timing additively on the Phase 8 Concept DTO."""

    latest = db.scalar(select(SemanticConceptVersion).where(
        SemanticConceptVersion.semantic_concept_id == concept.id,
        SemanticConceptVersion.project_id == concept.project_id,
    ).order_by(SemanticConceptVersion.version_no.desc(), SemanticConceptVersion.id.desc()).limit(1))
    if latest is not None:
        concept.current_version_no = latest.version_no
        concept.effective_from = latest.effective_from
        concept.effective_to = latest.effective_to
    return concept
