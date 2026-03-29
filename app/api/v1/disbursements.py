"""CRUD de desembolsos."""
import logging
from typing import List, Optional
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from dateutil.relativedelta import relativedelta

from app.database import get_db
from app.models.disbursement import Disbursement
from app.models.balance import Balance
from app.models.contract import Contract
from app.models.user import User
from pydantic import BaseModel
from app.schemas.disbursement import DisbursementCreate, DisbursementResponse
from app.security import get_current_user


class DisbursementUpdate(BaseModel):
    disbursement_name: Optional[str] = None
    status: Optional[str] = None
    spread_bps_override: Optional[Decimal] = None
    interest_rate_type_override: Optional[str] = None
    grace_period_months: Optional[int] = None
    notes: Optional[str] = None
from app.services.payment_generator import PaymentGenerator
from app.services.projection_engine import ProjectionEngine
from app.services.cache_service import CacheService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/disbursements", tags=["Desembolsos"])


def _auto_generate_schedule(db: Session, disbursement: Disbursement, contract: Contract) -> dict:
    """Genera pagos, balance inicial y proyecciones para un desembolso nuevo."""
    result = {"payments_created": 0, "balances_created": 0}
    try:
        # base_rate is a string like "SOFR", not a number; use 0 as base for spread-only calculation
        base_rate_bps = Decimal("0")
        payments = PaymentGenerator.generate_schedule(db, disbursement.id, base_rate_bps)
        result["payments_created"] = len(payments)

        # Crear balance inicial (mes de desembolso) para que ProjectionEngine tenga punto de partida
        disb_month_end = disbursement.disbursement_date.replace(day=28) + relativedelta(days=4)
        disb_month_end = disb_month_end.replace(day=1) - relativedelta(days=1)  # ultimo dia del mes

        spread = disbursement.spread_bps_override if disbursement.spread_bps_override is not None else (contract.spread_bps or Decimal("0"))
        days_to_maturity = (disbursement.maturity_date - disb_month_end).days
        residual_term = Decimal(max(days_to_maturity, 0)) / Decimal("365.25")

        initial_balance = Balance(
            disbursement_id=disbursement.id,
            period_date=disb_month_end,
            outstanding_original=disbursement.amount_original,
            outstanding_usd=disbursement.amount_usd,
            exchange_rate_used=disbursement.exchange_rate or Decimal("1"),
            residual_term_years=residual_term,
            spread_bps=spread,
            amortization_usd=Decimal("0"),
            interest_usd=Decimal("0"),
            debt_service_usd=Decimal("0"),
            is_projected=False,
            is_active=True,
        )
        db.add(initial_balance)
        db.commit()
        result["balances_created"] += 1

        # Proyectar hacia adelante
        projected = ProjectionEngine.project_disbursement(
            db, disbursement,
            from_date=disb_month_end + relativedelta(months=1),
            to_date=disbursement.maturity_date + relativedelta(months=1),
            force_regenerate=True,
        )
        result["balances_created"] += len(projected)

        CacheService.invalidate_pattern("dashboard:*")
    except Exception as e:
        logger.warning(f"Error generando cronograma para desembolso {disbursement.id}: {e}")
        db.rollback()

    return result


def _enrich_disbursement(disb: Disbursement) -> dict:
    """Add effective_spread_bps and contract_spread_bps to disbursement."""
    data = {c.key: getattr(disb, c.key) for c in disb.__table__.columns}
    contract_spread = disb.contract.spread_bps if disb.contract else None
    data["contract_spread_bps"] = contract_spread
    data["effective_spread_bps"] = disb.spread_bps_override if disb.spread_bps_override is not None else contract_spread
    return data


@router.get("", response_model=List[DisbursementResponse])
def list_disbursements(
    excel_sheet: Optional[str] = Query(None, description="IFD o Mercado"),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista desembolsos con filtros opcionales y paginación."""
    q = db.query(Disbursement).options(joinedload(Disbursement.contract))
    if excel_sheet:
        q = q.filter(Disbursement.excel_sheet == excel_sheet)
    if status:
        q = q.filter(Disbursement.status == status)
    disbursements = q.order_by(Disbursement.disbursement_code).offset(skip).limit(limit).all()
    return [_enrich_disbursement(d) for d in disbursements]


@router.get("/{disbursement_id}", response_model=DisbursementResponse)
def get_disbursement(disbursement_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Detalle de un desembolso."""
    disb = (
        db.query(Disbursement)
        .options(joinedload(Disbursement.contract))
        .filter(Disbursement.id == disbursement_id)
        .first()
    )
    if not disb:
        raise HTTPException(status_code=404, detail="Desembolso no encontrado")
    return _enrich_disbursement(disb)


@router.post("", response_model=DisbursementResponse, status_code=201)
def create_disbursement(data: DisbursementCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Crear nuevo desembolso."""
    # Validar contrato existe
    contract = db.query(Contract).filter(Contract.id == data.contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")

    # Validar código único
    existing = (
        db.query(Disbursement)
        .filter(Disbursement.disbursement_code == data.disbursement_code)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe desembolso con código {data.disbursement_code}",
        )

    disbursement = Disbursement(**data.model_dump())
    db.add(disbursement)
    db.commit()
    db.refresh(disbursement)

    # Auto-generar pagos y balances
    gen_result = _auto_generate_schedule(db, disbursement, contract)
    logger.info(f"Desembolso {disbursement.id} creado: {gen_result}")

    db.refresh(disbursement)
    enriched = _enrich_disbursement(disbursement)
    enriched["generation_result"] = gen_result
    return enriched


@router.put("/{disbursement_id}", response_model=DisbursementResponse)
def update_disbursement(
    disbursement_id: int,
    data: DisbursementUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Actualiza un desembolso existente."""
    disbursement = (
        db.query(Disbursement)
        .filter(Disbursement.id == disbursement_id)
        .first()
    )
    if not disbursement:
        raise HTTPException(status_code=404, detail="Desembolso no encontrado")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(disbursement, field, value)

    disbursement.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(disbursement)
    return disbursement


@router.get("/{disbursement_id}/balances")
def get_disbursement_balances(
    disbursement_id: int,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Serie temporal de saldos de un desembolso especifico."""
    disb = db.query(Disbursement).filter(Disbursement.id == disbursement_id).first()
    if not disb:
        raise HTTPException(status_code=404, detail="Desembolso no encontrado")

    q = db.query(Balance).filter(Balance.disbursement_id == disbursement_id)
    if date_from:
        q = q.filter(Balance.period_date >= date_from)
    if date_to:
        q = q.filter(Balance.period_date <= date_to)

    balances = q.order_by(Balance.period_date).all()

    return [
        {
            "period_date": b.period_date,
            "outstanding_usd": float(b.outstanding_usd),
            "spread_bps": float(b.spread_bps) if b.spread_bps else None,
            "residual_term_years": float(b.residual_term_years) if b.residual_term_years else None,
            "amortization_usd": float(b.amortization_usd) if b.amortization_usd else None,
            "is_projected": b.is_projected,
        }
        for b in balances
    ]


@router.post("/{disbursement_id}/regenerate")
def regenerate_schedule(disbursement_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Regenera pagos, balances y proyecciones de un desembolso."""
    disbursement = (
        db.query(Disbursement)
        .options(joinedload(Disbursement.contract))
        .filter(Disbursement.id == disbursement_id)
        .first()
    )
    if not disbursement:
        raise HTTPException(status_code=404, detail="Desembolso no encontrado")

    contract = disbursement.contract
    if not contract:
        raise HTTPException(status_code=400, detail="Desembolso sin contrato asociado")

    # Limpiar pagos y balances existentes
    from app.models.payment import PaymentSchedule
    db.query(PaymentSchedule).filter(PaymentSchedule.disbursement_id == disbursement_id).delete()
    db.query(Balance).filter(Balance.disbursement_id == disbursement_id).delete()
    db.commit()

    result = _auto_generate_schedule(db, disbursement, contract)
    return result
