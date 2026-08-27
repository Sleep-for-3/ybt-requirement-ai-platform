from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DataSource
from app.schemas import (
    DataSourceCreate,
    DataSourceRead,
    DataSourceTestResponse,
    DataSourceUpdate,
    SafeSqlRequest,
    SafeSqlResponse,
)
from app.services.datasource_service import create_datasource, delete_datasource, test_datasource_connection, update_datasource
from app.services.connectors.diagnostics import diagnose_payload
from app.services.connectors.registry import connector_registry
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.db.safe_sql_executor import SafeSqlExecutor

router = APIRouter(tags=["datasources"])


@router.post("/projects/{project_id}/datasources", response_model=DataSourceRead)
def create_project_datasource(project_id: int, payload: DataSourceCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> DataSource:
    PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    try:
        return create_datasource(db, project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/datasources", response_model=list[DataSourceRead])
def list_project_datasources(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[DataSource]:
    PermissionService(db, principal).require_project_permission(project_id, "catalog.search")
    return list(db.scalars(select(DataSource).where(DataSource.project_id == project_id).order_by(DataSource.id.desc())).all())


@router.get("/projects/{project_id}/datasource-connectors")
def list_datasource_connectors(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "catalog.search")
    return connector_registry()


@router.post("/projects/{project_id}/datasources/connection-inspect", response_model=DataSourceTestResponse)
def inspect_datasource_connection(project_id: int, payload: DataSourceCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> DataSourceTestResponse:
    PermissionService(db, principal).require_project_permission(project_id, "catalog.manage")
    return DataSourceTestResponse(**diagnose_payload(project_id, payload))


@router.get("/datasources/{datasource_id}", response_model=DataSourceRead)
def get_datasource(datasource_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> DataSource:
    return _get_authorized_datasource(db, principal, datasource_id, "catalog.search")


@router.put("/datasources/{datasource_id}", response_model=DataSourceRead)
def update_datasource_api(datasource_id: int, payload: DataSourceUpdate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> DataSource:
    try:
        return update_datasource(db, _get_authorized_datasource(db, principal, datasource_id, "catalog.manage"), payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/datasources/{datasource_id}")
def delete_datasource_api(datasource_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict[str, str]:
    delete_datasource(db, _get_authorized_datasource(db, principal, datasource_id, "catalog.manage"))
    return {"status": "deleted"}


@router.post("/datasources/{datasource_id}/test", response_model=DataSourceTestResponse)
def test_datasource_api(datasource_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> DataSourceTestResponse:
    try:
        result = test_datasource_connection(db, _get_authorized_datasource(db, principal, datasource_id, "catalog.manage"))
        return DataSourceTestResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/datasources/{datasource_id}/execute-safe-query", response_model=SafeSqlResponse)
def execute_safe_query(datasource_id: int, payload: SafeSqlRequest, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> SafeSqlResponse:
    datasource = _get_authorized_datasource(db, principal, datasource_id, "catalog.manage")
    return SafeSqlExecutor(db).execute(datasource=datasource, sql=payload.sql, project_id=datasource.project_id, max_rows=payload.max_rows)


def _get_datasource_or_404(db: Session, datasource_id: int) -> DataSource:
    datasource = db.get(DataSource, datasource_id)
    if datasource is None:
        raise HTTPException(status_code=404, detail="Data source not found")
    return datasource


def _get_authorized_datasource(db: Session, principal: CurrentPrincipal, datasource_id: int, permission: str) -> DataSource:
    datasource = _get_datasource_or_404(db, datasource_id)
    PermissionService(db, principal).require_project_permission(datasource.project_id, permission)
    return datasource
