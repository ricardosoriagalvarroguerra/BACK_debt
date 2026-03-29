"""Endpoints del Dashboard - metricas y KPIs del portafolio."""
from datetime import date
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.dashboard_service import DashboardService
from app.schemas.dashboard import (
    PortfolioSummary, DebtCeilingStatus, TimeSeriesResponse,
    CompositionItem, TopInstrument, MaturityProfileItem, ContractingProfileItem,
    RiskProfileResponse, InterestCostYear,
)
from app.models.user import User
from app.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=PortfolioSummary)
def get_portfolio_summary(
    period_date: Optional[date] = Query(None, description="Fecha del periodo (YYYY-MM-DD). Default: ultimo periodo."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resumen ejecutivo del portafolio: saldos, spread PP, plazo PP por tipo."""
    svc = DashboardService(db)
    return svc.get_summary(period_date)


@router.get("/debt-ceiling", response_model=DebtCeilingStatus)
def get_debt_ceiling_status(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Estado del tope de endeudamiento con semaforo de riesgo."""
    svc = DashboardService(db)
    return svc.get_debt_ceiling_status(period_date)


@router.get("/time-series", response_model=TimeSeriesResponse)
def get_time_series(
    date_from: Optional[date] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Series temporales mensuales de circulante, spread PP y plazo PP."""
    svc = DashboardService(db)
    return svc.get_time_series(date_from, date_to)


@router.get("/composition", response_model=List[CompositionItem])
def get_composition(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Composicion del portafolio por acreedor y moneda."""
    svc = DashboardService(db)
    return svc.get_composition(period_date)


@router.get("/top-instruments", response_model=List[TopInstrument])
def get_top_instruments(
    period_date: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=66),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Top N instrumentos por saldo vigente."""
    svc = DashboardService(db)
    return svc.get_top_instruments(period_date, limit)


@router.get("/maturity-profile", response_model=List[MaturityProfileItem])
def get_maturity_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Perfil de vencimientos (maturity wall) por ano y acreedor."""
    svc = DashboardService(db)
    return svc.get_maturity_profile()


@router.get("/contracting-profile", response_model=List[ContractingProfileItem])
def get_contracting_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Spread PP y Plazo PP de contratación por año y tipo de acreedor."""
    svc = DashboardService(db)
    return svc.get_contracting_profile()


@router.get("/risk-profile", response_model=RiskProfileResponse)
def get_risk_profile(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Perfil de riesgo estructural: exposicion por moneda, tipo de tasa, amortizacion, plazo residual."""
    svc = DashboardService(db)
    return svc.get_risk_profile(period_date)


@router.get("/interest-cost", response_model=List[InterestCostYear])
def get_interest_cost(
    source: Optional[str] = Query(None, description="Filter: IFD, MERCADO, or None for all"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Costo de deuda anual: interes, servicio, spread PP por ano."""
    svc = DashboardService(db)
    return svc.get_interest_cost(source=source)
