"""Endpoints para manejo de escenarios y simulaciones."""
from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.scenario import Scenario, ScenarioAssumption, ScenarioResult
from app.schemas.scenario import (
    ScenarioCreate,
    ScenarioUpdate,
    ScenarioResponse,
    ScenarioWithAssumptions,
    ScenarioAssumptionCreate,
    ScenarioAssumptionResponse,
    ScenarioResultResponse,
    ScenarioCompareResponse,
)
from app.services.scenario_service import ScenarioService
from app.models.user import User
from app.security import get_current_user

router = APIRouter(prefix="/scenarios", tags=["Escenarios"])


@router.get("", response_model=List[ScenarioWithAssumptions])
def list_scenarios(
    is_base: Optional[bool] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Lista escenarios con filtros opcionales."""
    q = db.query(Scenario).options(joinedload(Scenario.assumptions))
    if is_base is not None:
        q = q.filter(Scenario.is_base == is_base)
    if status:
        q = q.filter(Scenario.status == status)
    results = q.order_by(Scenario.created_at.desc()).all()
    # Deduplicate from joinedload
    seen = set()
    unique_results = []
    for r in results:
        if r.id not in seen:
            seen.add(r.id)
            unique_results.append(r)
    return unique_results


@router.get("/{scenario_id}", response_model=ScenarioWithAssumptions)
def get_scenario(scenario_id: int, db: Session = Depends(get_db)):
    """Obtiene un escenario con sus assumptions."""
    scenario = (
        db.query(Scenario)
        .options(joinedload(Scenario.assumptions))
        .filter(Scenario.id == scenario_id)
        .first()
    )
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")
    return scenario


@router.post("", response_model=ScenarioResponse, status_code=201)
def create_scenario(
    data: ScenarioCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Crea un nuevo escenario."""
    scenario = ScenarioService.create_scenario(
        db,
        name=data.name,
        description=data.description,
        is_base=data.is_base,
        created_by=user.id,
    )

    # Crear assumptions si se proporcionan
    for assumption_data in data.assumptions:
        ScenarioService.add_assumption(
            db,
            scenario.id,
            assumption_data.model_dump(),
        )

    db.refresh(scenario)
    return scenario


@router.put("/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(
    scenario_id: int,
    data: ScenarioUpdate,
    db: Session = Depends(get_db),
):
    """Actualiza un escenario."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(scenario, field, value)

    db.commit()
    db.refresh(scenario)
    return scenario


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Elimina un escenario y todas sus assumptions/results."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")
    db.delete(scenario)
    db.commit()
    return None


@router.post("/{scenario_id}/assumptions", response_model=ScenarioAssumptionResponse, status_code=201)
def add_assumption(
    scenario_id: int,
    data: ScenarioAssumptionCreate,
    db: Session = Depends(get_db),
):
    """Añade una assumption a un escenario."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")

    assumption = ScenarioService.add_assumption(
        db,
        scenario_id,
        data.model_dump(),
    )
    return assumption


@router.get("/{scenario_id}/assumptions", response_model=List[ScenarioAssumptionResponse])
def get_assumptions(scenario_id: int, db: Session = Depends(get_db)):
    """Obtiene las assumptions de un escenario."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")

    assumptions = (
        db.query(ScenarioAssumption)
        .filter(ScenarioAssumption.scenario_id == scenario_id)
        .order_by(ScenarioAssumption.assumption_order)
        .all()
    )
    return assumptions


@router.post("/{scenario_id}/run", status_code=201)
def run_simulation(
    scenario_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
):
    """Ejecuta la simulación de un escenario."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")

    try:
        results = ScenarioService.run_simulation(
            db,
            scenario_id,
            from_date,
            to_date,
        )
        return {
            "scenario_id": scenario_id,
            "results_count": len(results),
            "from_date": from_date,
            "to_date": to_date,
            "status": "success",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{scenario_id}/results", response_model=List[ScenarioResultResponse])
def get_scenario_results(
    scenario_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Obtiene los resultados de una simulación."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Escenario no encontrado")

    q = db.query(ScenarioResult).filter(ScenarioResult.scenario_id == scenario_id)
    if from_date:
        q = q.filter(ScenarioResult.period_date >= from_date)
    if to_date:
        q = q.filter(ScenarioResult.period_date <= to_date)

    results = q.order_by(ScenarioResult.period_date).all()
    return results


@router.post("/compare", response_model=List[ScenarioCompareResponse])
def compare_scenarios(
    scenario_ids: List[int] = Query(...),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Compara múltiples escenarios."""
    if not scenario_ids:
        raise HTTPException(status_code=400, detail="Se requieren scenario_ids")

    if from_date is None or to_date is None:
        raise HTTPException(status_code=400, detail="Se requieren from_date y to_date")

    comparison = ScenarioService.compare_scenarios(
        db,
        scenario_ids,
        from_date,
        to_date,
    )

    response = []
    for name, data in comparison.items():
        scenario_compare = ScenarioCompareResponse(
            scenario_id=data["scenario_id"],
            scenario_name=name,
            results=data["results"],
        )
        response.append(scenario_compare)

    return response
