from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, TargetTable
from app.services.export import export_traceability_workbook
from app.services.auth.dependencies import CurrentPrincipal
from app.services.governance.audit import record_audit

router = APIRouter(tags=["traceability export"])
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/projects/{project_id}/export/traceability-workbook")
def export_project_traceability(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    content = export_traceability_workbook(db, project_id); file_name = f"{project.name}-业务口径及技术溯源表.xlsx"
    record_audit(db, action="export", resource_type="traceability_workbook", resource_id=project_id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id, after={"file_name": file_name, "scope": "project", "byte_size": len(content)})
    db.commit(); return _response(content, file_name)


@router.get("/target-tables/{table_id}/export/traceability-workbook")
def export_table_traceability(table_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Response:
    table = db.get(TargetTable, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Target table not found")
    project = db.get(Project, table.project_id);content = export_traceability_workbook(db, table.project_id, table_id);file_name=f"{table.table_name}-业务口径及技术溯源表.xlsx"
    record_audit(db, action="export", resource_type="traceability_workbook", resource_id=table_id, actor_user_id=principal.user_id, institution_id=project.institution_id if project else None, project_id=table.project_id, after={"file_name": file_name, "scope": "target_table", "byte_size": len(content)})
    db.commit();return _response(content,file_name)


def _response(content: bytes, file_name: str) -> Response:
    return Response(content=content, media_type=CONTENT_TYPE, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"
    })
