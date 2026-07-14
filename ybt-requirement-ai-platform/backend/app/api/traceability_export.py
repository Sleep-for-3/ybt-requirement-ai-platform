from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, TargetTable
from app.services.export import export_traceability_workbook

router = APIRouter(tags=["traceability export"])
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/projects/{project_id}/export/traceability-workbook")
def export_project_traceability(project_id: int, db: Session = Depends(get_db)) -> Response:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _response(export_traceability_workbook(db, project_id), f"{project.name}-业务口径及技术溯源表.xlsx")


@router.get("/target-tables/{table_id}/export/traceability-workbook")
def export_table_traceability(table_id: int, db: Session = Depends(get_db)) -> Response:
    table = db.get(TargetTable, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Target table not found")
    return _response(export_traceability_workbook(db, table.project_id, table_id), f"{table.table_name}-业务口径及技术溯源表.xlsx")


def _response(content: bytes, file_name: str) -> Response:
    return Response(content=content, media_type=CONTENT_TYPE, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"
    })
