from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ProductScenario, Project
from app.schemas import ProductScenarioCreate, ProductScenarioRead, ProductScenarioUpdate

router = APIRouter(tags=["product scenarios"])


@router.post("/projects/{project_id}/scenarios", response_model=ProductScenarioRead)
def create_scenario(project_id: int, payload: ProductScenarioCreate, db: Session = Depends(get_db)) -> ProductScenario:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    scenario = ProductScenario(project_id=project_id, **payload.model_dump())
    db.add(scenario)
    _commit_or_conflict(db)
    db.refresh(scenario)
    return scenario


@router.get("/projects/{project_id}/scenarios", response_model=list[ProductScenarioRead])
def list_scenarios(project_id: int, enabled: bool | None = None, db: Session = Depends(get_db)) -> list[ProductScenario]:
    statement = select(ProductScenario).where(ProductScenario.project_id == project_id)
    if enabled is not None:
        statement = statement.where(ProductScenario.enabled == enabled)
    return list(db.scalars(statement.order_by(ProductScenario.sort_order, ProductScenario.id)).all())


@router.get("/scenarios/{scenario_id}", response_model=ProductScenarioRead)
def get_scenario(scenario_id: int, db: Session = Depends(get_db)) -> ProductScenario:
    return _get_scenario_or_404(db, scenario_id)


@router.put("/scenarios/{scenario_id}", response_model=ProductScenarioRead)
def update_scenario(scenario_id: int, payload: ProductScenarioUpdate, db: Session = Depends(get_db)) -> ProductScenario:
    scenario = _get_scenario_or_404(db, scenario_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(scenario, key, value)
    _commit_or_conflict(db)
    db.refresh(scenario)
    return scenario


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    scenario = _get_scenario_or_404(db, scenario_id)
    db.delete(scenario)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Scenario is already in use") from exc
    return {"status": "deleted"}


def _get_scenario_or_404(db: Session, scenario_id: int) -> ProductScenario:
    scenario = db.get(ProductScenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="scenario_code must be unique within a project") from exc
