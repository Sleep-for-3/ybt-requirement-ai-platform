from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import MappingDocumentExportRead
from app.services.mapping.exporter import export_field_mapping_document, export_project_mapping_document, export_table_mapping_document

router = APIRouter(tags=["mapping export"])


@router.get("/projects/{project_id}/export/mapping-document", response_model=MappingDocumentExportRead)
def export_project_mapping(
    project_id: int,
    format: str = Query(default="markdown"),
    db: Session = Depends(get_db),
) -> MappingDocumentExportRead:
    _ensure_markdown(format)
    try:
        content = export_project_mapping_document(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MappingDocumentExportRead(format="markdown", scope="project", scope_id=project_id, file_name=f"project-{project_id}-mapping.md", content=content)


@router.get("/target-tables/{table_id}/export/mapping-document", response_model=MappingDocumentExportRead)
def export_table_mapping(
    table_id: int,
    format: str = Query(default="markdown"),
    db: Session = Depends(get_db),
) -> MappingDocumentExportRead:
    _ensure_markdown(format)
    try:
        content = export_table_mapping_document(db, table_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MappingDocumentExportRead(format="markdown", scope="target_table", scope_id=table_id, file_name=f"target-table-{table_id}-mapping.md", content=content)


@router.get("/target-fields/{field_id}/export/mapping-document", response_model=MappingDocumentExportRead)
def export_field_mapping(
    field_id: int,
    format: str = Query(default="markdown"),
    db: Session = Depends(get_db),
) -> MappingDocumentExportRead:
    _ensure_markdown(format)
    try:
        content = export_field_mapping_document(db, field_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MappingDocumentExportRead(format="markdown", scope="target_field", scope_id=field_id, file_name=f"target-field-{field_id}-mapping.md", content=content)


def _ensure_markdown(format: str) -> None:
    if format != "markdown":
        raise HTTPException(status_code=400, detail="Only markdown export is supported in this MVP")
