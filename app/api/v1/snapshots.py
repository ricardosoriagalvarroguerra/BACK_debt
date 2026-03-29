"""Portfolio Snapshot endpoints - Cortes del portafolio por fecha."""
from datetime import date
from decimal import Decimal
from typing import Optional, List, Literal
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract, distinct

from app.database import get_db
from app.models.user import User
from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor
from app.models.config import SystemConfig
from app.security import get_current_user

router = APIRouter(prefix="/snapshots", tags=["Cortes de Portafolio"])


@router.get("/available-periods")
def get_available_periods(
    granularity: Literal["mensual", "trimestral", "semestral", "anual"] = Query("mensual"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get available period dates based on granularity."""
    month_filter = {
        "mensual": list(range(1, 13)),
        "trimestral": [3, 6, 9, 12],
        "semestral": [6, 12],
        "anual": [12],
    }
    months = month_filter[granularity]

    # Get all period_dates that have at least 1 instrument with outstanding > 0
    rows = (
        db.query(
            Balance.period_date,
            func.count(distinct(Balance.disbursement_id)).label("instruments"),
        )
        .filter(
            extract("month", Balance.period_date).in_(months),
            extract("day", Balance.period_date).in_([28, 29, 30, 31]),  # end-of-month only
            Balance.outstanding_usd > 0,
        )
        .group_by(Balance.period_date)
        .having(func.count(distinct(Balance.disbursement_id)) >= 1)
        .order_by(Balance.period_date.desc())
        .all()
    )

    return [
        {"period_date": r.period_date.isoformat(), "instruments": r.instruments}
        for r in rows
    ]


@router.get("/history")
def get_history_up_to(
    period_date: date = Query(...),
    granularity: Literal["mensual", "trimestral", "semestral", "anual"] = Query("trimestral"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Historical series up to the selected cut date: stock by source, amortization profile, debt service flow."""
    month_filter = {
        "mensual": list(range(1, 13)),
        "trimestral": [3, 6, 9, 12],
        "semestral": [6, 12],
        "anual": [12],
    }
    months = month_filter[granularity]

    # Stock evolution by source (IFD vs Mercado) up to cut date
    rows = (
        db.query(
            Balance.period_date,
            Creditor.creditor_type,
            func.sum(Balance.outstanding_usd).label("outstanding"),
        )
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date <= period_date,
            Balance.outstanding_usd > 0,
            extract("month", Balance.period_date).in_(months),
            extract("day", Balance.period_date).in_([28, 29, 30, 31]),
            Disbursement.status == "DESEMBOLSADO",
        )
        .group_by(Balance.period_date, Creditor.creditor_type)
        .order_by(Balance.period_date)
        .all()
    )

    # Build stock series
    stock_map: dict = {}
    for r in rows:
        d = r.period_date.isoformat()
        if d not in stock_map:
            stock_map[d] = {"period_date": d, "ifd": 0, "mercado": 0, "total": 0}
        val = float(r.outstanding)
        if r.creditor_type == "IFD":
            stock_map[d]["ifd"] = round(val, 2)
        else:
            stock_map[d]["mercado"] = round(val, 2)
        stock_map[d]["total"] = round(stock_map[d]["ifd"] + stock_map[d]["mercado"], 2)

    stock_series = list(stock_map.values())

    # Amortization profile: principal payments by year up to cut date, split by source
    amort_rows = (
        db.query(
            extract("year", Balance.period_date).label("year"),
            Creditor.creditor_type,
            func.sum(Balance.amortization_usd).label("amort"),
        )
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date <= period_date,
            Balance.amortization_usd > 0,
            Disbursement.status == "DESEMBOLSADO",
        )
        .group_by(extract("year", Balance.period_date), Creditor.creditor_type)
        .order_by(extract("year", Balance.period_date))
        .all()
    )

    amort_map: dict = {}
    for r in amort_rows:
        yr = int(r.year)
        if yr not in amort_map:
            amort_map[yr] = {"year": yr, "ifd": 0, "mercado": 0}
        val = float(r.amort)
        if r.creditor_type == "IFD":
            amort_map[yr]["ifd"] = round(val, 2)
        else:
            amort_map[yr]["mercado"] = round(val, 2)

    amort_series = list(amort_map.values())

    # Debt service flow ANNUAL (always by year), up to cut date
    flow_rows = (
        db.query(
            extract("year", Balance.period_date).label("year"),
            Creditor.creditor_type,
            func.sum(Balance.amortization_usd).label("principal"),
            func.sum(Balance.interest_usd).label("interest"),
        )
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date <= period_date,
            Disbursement.status == "DESEMBOLSADO",
        )
        .group_by(extract("year", Balance.period_date), Creditor.creditor_type)
        .order_by(extract("year", Balance.period_date))
        .all()
    )

    flow_map: dict = {}
    for r in flow_rows:
        yr = int(r.year)
        if yr not in flow_map:
            flow_map[yr] = {"year": yr, "ifd_principal": 0, "ifd_interest": 0, "mercado_principal": 0, "mercado_interest": 0}
        p = float(r.principal or 0)
        i = float(r.interest or 0)
        if r.creditor_type == "IFD":
            flow_map[yr]["ifd_principal"] = round(p, 2)
            flow_map[yr]["ifd_interest"] = round(i, 2)
        else:
            flow_map[yr]["mercado_principal"] = round(p, 2)
            flow_map[yr]["mercado_interest"] = round(i, 2)

    flow_series = list(flow_map.values())

    return {
        "period_date": period_date.isoformat(),
        "stock_series": stock_series,
        "amort_profile": amort_series,
        "flow_series": flow_series,
    }


@router.get("/snapshot")
def get_portfolio_snapshot(
    period_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full portfolio snapshot for a specific date."""
    balances = (
        db.query(Balance)
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date == period_date,
            Disbursement.status == "DESEMBOLSADO",
            Balance.outstanding_usd > 0,
        )
        .options(
            joinedload(Balance.disbursement)
            .joinedload(Disbursement.contract)
            .joinedload(Contract.creditor)
        )
        .all()
    )

    if not balances:
        raise HTTPException(404, f"No hay datos para {period_date}")

    # --- KPIs ---
    total_outstanding = Decimal(0)
    ifd_outstanding = Decimal(0)
    market_outstanding = Decimal(0)
    w_spread = Decimal(0)
    w_term = Decimal(0)
    w_total = Decimal(0)
    total_amort = Decimal(0)
    total_interest = Decimal(0)
    total_ds = Decimal(0)

    # --- By creditor ---
    by_creditor: dict = {}
    # --- By currency ---
    by_currency: dict = {}
    # --- By amort type ---
    by_amort: dict = {}
    # --- Instruments detail ---
    instruments = []

    for b in balances:
        d = b.disbursement
        c = d.contract
        cr = c.creditor
        cur_code = c.currency.code if hasattr(c, 'currency') and c.currency else "USD"

        outstanding = b.outstanding_usd or Decimal(0)
        total_outstanding += outstanding
        total_amort += b.amortization_usd or Decimal(0)
        total_interest += b.interest_usd or Decimal(0)
        total_ds += b.debt_service_usd or Decimal(0)

        ctype = cr.creditor_type if cr else "IFD"
        if ctype == "IFD":
            ifd_outstanding += outstanding
        else:
            market_outstanding += outstanding

        if outstanding > 0:
            if b.spread_bps:
                w_spread += b.spread_bps * outstanding
            if b.residual_term_years:
                w_term += b.residual_term_years * outstanding
            w_total += outstanding

        # By creditor
        cname = cr.short_name or cr.code if cr else "N/A"
        if cname not in by_creditor:
            by_creditor[cname] = {"outstanding": Decimal(0), "count": 0, "type": ctype}
        by_creditor[cname]["outstanding"] += outstanding
        by_creditor[cname]["count"] += 1

        # By currency - use currency from balance/contract
        try:
            currency = db.query(Creditor).get(cr.id)  # just reuse creditor
            from app.models.currency import Currency
            cur = db.query(Currency).filter(Currency.id == c.currency_id).first()
            cur_code = cur.code if cur else "USD"
        except Exception:
            cur_code = "USD"

        if cur_code not in by_currency:
            by_currency[cur_code] = {"outstanding": Decimal(0), "count": 0}
        by_currency[cur_code]["outstanding"] += outstanding
        by_currency[cur_code]["count"] += 1

        # By amort type
        atype = c.amortization_type or "BULLET"
        if atype not in by_amort:
            by_amort[atype] = {"outstanding": Decimal(0), "count": 0}
        by_amort[atype]["outstanding"] += outstanding
        by_amort[atype]["count"] += 1

        # Instrument detail
        instruments.append({
            "code": d.disbursement_code,
            "name": d.disbursement_name,
            "creditor": cname,
            "creditor_type": ctype,
            "outstanding_usd": float(outstanding),
            "spread_bps": float(b.spread_bps) if b.spread_bps else None,
            "residual_term": float(b.residual_term_years) if b.residual_term_years else None,
            "maturity_date": d.maturity_date.isoformat() if d.maturity_date else None,
            "amort_type": c.amortization_type,
            "currency": cur_code,
            "amortization_usd": float(b.amortization_usd or 0),
            "interest_usd": float(b.interest_usd or 0),
        })

    # Ceiling
    ceiling_row = db.query(SystemConfig).filter(SystemConfig.key == "debt_ceiling_usd_mm").first()
    ceiling_limit = float(ceiling_row.value) if ceiling_row else 2500.0
    ceiling_pct = (float(total_outstanding) / ceiling_limit * 100) if ceiling_limit > 0 else 0

    # Covenant status (simplified)
    from app.models.covenant import Covenant
    covenants = db.query(Covenant).filter(Covenant.is_active == True).all()
    covenant_status = []
    for cov in covenants:
        current_val = None
        status = "SIN_DATOS"
        if cov.covenant_type == "TOPE_ENDEUDAMIENTO":
            current_val = float(total_outstanding)
            pct = (current_val / float(cov.limit_value) * 100) if cov.limit_value else 0
            status = "VERDE" if pct <= 80 else ("AMARILLO" if pct <= 90 else ("NARANJA" if pct <= 100 else "ROJO"))
        covenant_status.append({
            "name": cov.name,
            "type": cov.covenant_type,
            "limit_value": float(cov.limit_value),
            "current_value": current_val,
            "status": status,
        })

    avg_spread = float(w_spread / w_total) if w_total > 0 else 0
    avg_term = float(w_term / w_total) if w_total > 0 else 0

    # Sort instruments by outstanding desc
    instruments.sort(key=lambda x: x["outstanding_usd"], reverse=True)

    return {
        "period_date": period_date.isoformat(),
        "kpis": {
            "total_outstanding_usd": float(total_outstanding),
            "ifd_outstanding_usd": float(ifd_outstanding),
            "market_outstanding_usd": float(market_outstanding),
            "weighted_avg_spread_bps": round(avg_spread, 2),
            "weighted_avg_term_years": round(avg_term, 2),
            "ceiling_pct": round(ceiling_pct, 2),
            "ceiling_limit_usd": ceiling_limit,
            "ceiling_status": "VERDE" if ceiling_pct <= 80 else ("AMARILLO" if ceiling_pct <= 90 else ("NARANJA" if ceiling_pct <= 100 else "ROJO")),
            "total_amortization_usd": float(total_amort),
            "total_interest_usd": float(total_interest),
            "total_debt_service_usd": float(total_ds),
            "instrument_count": len(instruments),
        },
        "by_creditor": [
            {"creditor": k, "type": v["type"], "outstanding_usd": float(v["outstanding"]), "count": v["count"],
             "pct": round(float(v["outstanding"]) / float(total_outstanding) * 100, 1) if total_outstanding > 0 else 0}
            for k, v in sorted(by_creditor.items(), key=lambda x: x[1]["outstanding"], reverse=True)
        ],
        "by_currency": [
            {"currency": k, "outstanding_usd": float(v["outstanding"]), "count": v["count"],
             "pct": round(float(v["outstanding"]) / float(total_outstanding) * 100, 1) if total_outstanding > 0 else 0}
            for k, v in sorted(by_currency.items(), key=lambda x: x[1]["outstanding"], reverse=True)
        ],
        "by_amort_type": [
            {"amort_type": k, "outstanding_usd": float(v["outstanding"]), "count": v["count"],
             "pct": round(float(v["outstanding"]) / float(total_outstanding) * 100, 1) if total_outstanding > 0 else 0}
            for k, v in sorted(by_amort.items(), key=lambda x: x[1]["outstanding"], reverse=True)
        ],
        "covenants": covenant_status,
        "instruments": instruments,
    }
