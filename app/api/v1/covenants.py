"""Endpoints de covenants y restricciones."""
from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.covenant import Covenant, CovenantTracking
from app.models.user import User
from app.schemas.covenant import CovenantResponse, CovenantStatusResponse, CovenantTrackingResponse
from app.security import get_current_user
from app.services.covenant_service import CovenantService

router = APIRouter(prefix="/covenants", tags=["Covenants"])


@router.get("", response_model=List[CovenantResponse])
def list_covenants(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Lista todos los covenants activos."""
    covenants = db.query(Covenant).filter(Covenant.is_active == True).all()
    return covenants


@router.get("/{covenant_id}", response_model=CovenantResponse)
def get_covenant(covenant_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Obtiene un covenant específico."""
    covenant = db.query(Covenant).filter(Covenant.id == covenant_id).first()
    if not covenant:
        raise HTTPException(status_code=404, detail="Covenant no encontrado")
    return covenant


@router.get("/{covenant_id}/status", response_model=CovenantStatusResponse)
def get_covenant_status(
    covenant_id: int,
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Obtiene el status actual de un covenant."""
    covenant = db.query(Covenant).filter(Covenant.id == covenant_id).first()
    if not covenant:
        raise HTTPException(status_code=404, detail="Covenant no encontrado")

    status_data = CovenantService.get_covenant_status(db, covenant_id, period_date)

    if not status_data:
        raise HTTPException(status_code=400, detail="No se pudo evaluar el covenant")

    return status_data


@router.get("/{covenant_id}/history", response_model=List[CovenantTrackingResponse])
def get_covenant_history(
    covenant_id: int,
    limit: int = Query(12, ge=1, le=120),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Obtiene el historial de un covenant (últimos N períodos)."""
    covenant = db.query(Covenant).filter(Covenant.id == covenant_id).first()
    if not covenant:
        raise HTTPException(status_code=404, detail="Covenant no encontrado")

    history = (
        db.query(CovenantTracking)
        .filter(CovenantTracking.covenant_id == covenant_id)
        .order_by(CovenantTracking.period_date.desc())
        .limit(limit)
        .all()
    )

    return list(reversed(history))


@router.post("/{covenant_id}/track", status_code=201)
def track_covenant(
    covenant_id: int,
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Registra el tracking de un covenant para una fecha."""
    covenant = db.query(Covenant).filter(Covenant.id == covenant_id).first()
    if not covenant:
        raise HTTPException(status_code=404, detail="Covenant no encontrado")

    tracking = CovenantService.track_covenant(db, covenant_id, period_date)

    if not tracking:
        raise HTTPException(status_code=400, detail="No se pudo registrar el tracking")

    return {
        "covenant_id": covenant_id,
        "period_date": tracking.period_date,
        "status": tracking.status,
        "current_value": float(tracking.current_value),
        "utilization_pct": float(tracking.utilization_pct) if tracking.utilization_pct else None,
    }


@router.post("/batch-evaluate", status_code=200)
def batch_evaluate_covenants(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Evalúa todos los covenants activos para una fecha."""
    results = CovenantService.batch_evaluate_covenants(db, period_date or date.today())

    response_data = []
    for covenant_id, status_data in results.items():
        response_data.append({
            "covenant_id": covenant_id,
            "covenant_name": status_data["covenant"].name,
            "status": status_data["status"],
            "traffic_light": status_data["traffic_light"],
            "current_value": float(status_data.get("current_value") or 0),
            "utilization_pct": float(status_data.get("utilization_pct") or 0),
        })

    return {
        "period_date": period_date or date.today(),
        "total_covenants": len(response_data),
        "covenants": response_data,
    }
