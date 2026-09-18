from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services import data_architecture as service

router = APIRouter(tags=["data architecture"])


class ArchitectureWrite(BaseModel):
    definition: dict
    expected_version: int = Field(ge=0)


class AssignmentWrite(BaseModel):
    layer_key: str | None = None
    business_system_id: int | None = None
    target_table_id: int | None = None
    template_version_id: int | None = None
    architecture_version: int = Field(ge=1)


class SuggestionRule(BaseModel):
    layer_key: str = Field(max_length=64)
    database_name: str | None = Field(default=None, max_length=255)
    schema_name: str | None = Field(default=None, max_length=255)
    table_prefix: str | None = Field(default=None, max_length=255)


class SuggestionRequest(BaseModel):
    rules: list[SuggestionRule] = Field(min_length=1, max_length=100)


def serialized(row):
    return {"id": row.id, "version": row.version, "definition": row.definition_json} if row else {"id": None, "version": 0, "definition": None}


@router.get("/projects/{project_id}/data-architecture")
def read_project(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return {**serialized(service.get_architecture(db, project_id=project_id)), "institution_id": project.institution_id, "examples": service.examples(),
            "tables": service.table_classifications(db, project_id)}


@router.put("/projects/{project_id}/data-architecture")
def write_project(project_id: int, payload: ArchitectureWrite, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    row = service.save_architecture(db, payload.definition, payload.expected_version, project_id=project_id)
    db.commit()
    return serialized(row)


@router.get("/projects/{project_id}/data-architecture/classification-options")
def classification_options(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    return service.classification_options(db, project_id)


@router.post("/projects/{project_id}/data-architecture/copy-institution")
def copy_template(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    project = PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    row = service.copy_institution_template(db, project)
    db.commit()
    return serialized(row)


@router.get("/institutions/{institution_id}/data-architecture")
def read_institution(institution_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_institution_role(institution_id, {"institution_admin", "security_admin", "member", "auditor"})
    return {**serialized(service.get_architecture(db, institution_id=institution_id)), "examples": service.examples()}


@router.put("/institutions/{institution_id}/data-architecture")
def write_institution(institution_id: int, payload: ArchitectureWrite, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_institution_role(institution_id, {"institution_admin"})
    row = service.save_architecture(db, payload.definition, payload.expected_version, institution_id=institution_id)
    db.commit()
    return serialized(row)


@router.put("/projects/{project_id}/catalog/tables/{table_id}/classification")
def classify(project_id: int, table_id: int, payload: AssignmentWrite, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    row = service.assign_table(db, project_id, table_id, payload.model_dump(exclude={"architecture_version"}), payload.architecture_version)
    db.commit()
    return {"catalog_table_id": table_id, "assignment": row.assignment_json, "architecture_revision_id": row.architecture_revision_id}


@router.post("/projects/{project_id}/data-architecture/suggestions")
def suggestions(project_id: int, payload: SuggestionRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    return service.suggest_classifications(db, project_id, [rule.model_dump() for rule in payload.rules])
