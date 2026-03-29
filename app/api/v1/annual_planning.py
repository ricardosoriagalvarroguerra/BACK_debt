"""Annual Debt Planning Wizard endpoints."""
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.security import get_current_user
from app.schemas.annual_planning import (
    MaturityItem, QuickSimulateRequest, QuickSimulateResponse,
    SavePlanRequest,
)
from app.services.annual_planning_service import AnnualPlanningService

router = APIRouter(prefix="/annual-planning", tags=["Planificacion Anual"])


@router.get("/maturities", response_model=List[MaturityItem])
def get_maturities(
    year: int = Query(..., ge=2024, le=2060),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all instruments maturing in the given year."""
    return AnnualPlanningService.get_maturities_for_year(db, year)


@router.post("/quick-simulate", response_model=QuickSimulateResponse)
def quick_simulate(
    request: QuickSimulateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run quick in-memory simulation for real-time impact preview."""
    return AnnualPlanningService.quick_simulate(db, request)


@router.post("/save-plan")
def save_plan(
    request: SavePlanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save the annual plan as a scenario."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        scenario_id = AnnualPlanningService.save_as_scenario(db, request, user.id)
        return {"scenario_id": scenario_id, "message": f"Plan guardado como escenario #{scenario_id}"}
    except Exception as e:
        logger.error(f"Error saving plan: {e}", exc_info=True)
        db.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Error guardando plan: {str(e)}")
