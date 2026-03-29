"""Projection endpoints - Proyecciones de portafolio."""
from datetime import date
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from dateutil.relativedelta import relativedelta

from app.database import get_db
from app.models.user import User
from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor
from app.models.payment import PaymentSchedule
from app.security import get_current_user
from app.services.projection_engine import ProjectionEngine

router = APIRouter(prefix="/projections", tags=["Proyecciones"])


@router.get("/portfolio")
def get_portfolio_projection(
    as_of: Optional[date] = Query(None),
    months_ahead: int = Query(12, ge=1, le=360),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Proyección del portafolio N meses hacia adelante usando payment_schedule."""
    base_date = as_of or date.today()
    end_date = base_date + relativedelta(months=months_ahead)

    # Get all active disbursements with contract info
    disbursements = (
        db.query(Disbursement)
        .options(joinedload(Disbursement.contract).joinedload(Contract.creditor))
        .filter(Disbursement.status == "DESEMBOLSADO")
        .all()
    )

    # Get all scheduled principal payments in the projection window
    principal_payments = (
        db.query(
            PaymentSchedule.disbursement_id,
            PaymentSchedule.payment_date,
            PaymentSchedule.amount_usd,
        )
        .filter(
            PaymentSchedule.payment_type == "PRINCIPAL",
            PaymentSchedule.payment_date > base_date,
            PaymentSchedule.payment_date <= end_date,
        )
        .order_by(PaymentSchedule.payment_date)
        .all()
    )

    # Build amort map: disb_id -> [(date, amount)]
    amort_map: dict = {}
    for disb_id, pay_date, amount in principal_payments:
        amort_map.setdefault(disb_id, []).append((pay_date, amount))

    # Get current outstanding per disbursement from latest balance
    latest_balances = {}
    for d in disbursements:
        bal = (
            db.query(Balance)
            .filter(
                Balance.disbursement_id == d.id,
                Balance.period_date <= base_date,
            )
            .order_by(Balance.period_date.desc())
            .first()
        )
        if bal and bal.outstanding_usd > 0:
            latest_balances[d.id] = {
                "outstanding": bal.outstanding_usd,
                "disbursement": d,
            }

    # Build monthly projections
    projections = []
    current = base_date + relativedelta(months=1)
    # Track running balances
    running = {did: info["outstanding"] for did, info in latest_balances.items()}

    while current <= end_date:
        month_amort = Decimal(0)
        month_interest = Decimal(0)

        for did, balance in list(running.items()):
            if balance <= 0:
                continue
            disb_info = latest_balances.get(did)
            if not disb_info:
                continue
            d = disb_info["disbursement"]
            spread = d.effective_spread_bps or d.contract.spread_bps or Decimal(0)

            # Check if any amortization this month
            amort_this_month = Decimal(0)
            for pay_date, amount in amort_map.get(did, []):
                if pay_date.year == current.year and pay_date.month == current.month:
                    amort_this_month += amount

            # Interest on pre-amort balance
            interest = balance * spread / Decimal("10000") / Decimal("12")
            month_interest += interest
            month_amort += amort_this_month
            running[did] = max(balance - amort_this_month, Decimal(0))

        total_outstanding = sum(running.values())

        projections.append({
            "period_date": current.isoformat(),
            "outstanding_usd": float(total_outstanding),
            "amortization_usd": float(month_amort),
            "interest_usd": float(month_interest),
            "debt_service_usd": float(month_amort + month_interest),
        })

        current += relativedelta(months=1)

    return {
        "base_date": base_date.isoformat(),
        "months": months_ahead,
        "disbursement_count": len(latest_balances),
        "projections": projections,
    }


@router.post("/recalculate")
def recalculate_projections(
    as_of: Optional[date] = Query(None),
    months_ahead: int = Query(60, ge=1, le=360),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recalcula proyecciones usando ProjectionEngine."""
    base_date = as_of or date.today()
    end_date = base_date + relativedelta(months=months_ahead)

    total_created = ProjectionEngine.project_portfolio(db, base_date, end_date)

    return {
        "status": "ok",
        "base_date": base_date.isoformat(),
        "end_date": end_date.isoformat(),
        "records_updated": total_created,
    }


@router.get("/metrics")
def get_projection_metrics(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Métricas del portafolio para una fecha específica."""
    target_date = period_date or date.today()

    # Get balances for the target date
    balances = (
        db.query(Balance)
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date == target_date,
            Disbursement.status == "DESEMBOLSADO",
        )
        .options(
            joinedload(Balance.disbursement)
            .joinedload(Disbursement.contract)
            .joinedload(Contract.creditor)
        )
        .all()
    )

    if not balances:
        return {
            "date": target_date.isoformat(),
            "metrics": {
                "total_outstanding_usd": 0,
                "ifd_outstanding_usd": 0,
                "market_outstanding_usd": 0,
                "weighted_avg_spread_bps": 0,
                "weighted_avg_term_years": 0,
                "instrument_count": 0,
            },
        }

    total = Decimal(0)
    ifd = Decimal(0)
    market = Decimal(0)
    w_spread = Decimal(0)
    w_term = Decimal(0)
    w_total = Decimal(0)

    for bal in balances:
        total += bal.outstanding_usd
        ctype = bal.disbursement.contract.creditor.creditor_type
        if ctype == "IFD":
            ifd += bal.outstanding_usd
        else:
            market += bal.outstanding_usd

        if bal.outstanding_usd > 0:
            if bal.spread_bps:
                w_spread += bal.spread_bps * bal.outstanding_usd
            if bal.residual_term_years:
                w_term += bal.residual_term_years * bal.outstanding_usd
            w_total += bal.outstanding_usd

    return {
        "date": target_date.isoformat(),
        "metrics": {
            "total_outstanding_usd": float(total),
            "ifd_outstanding_usd": float(ifd),
            "market_outstanding_usd": float(market),
            "weighted_avg_spread_bps": float(w_spread / w_total) if w_total > 0 else 0,
            "weighted_avg_term_years": float(w_term / w_total) if w_total > 0 else 0,
            "instrument_count": len(balances),
        },
    }
