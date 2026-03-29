"""Endpoints para reportes y exportación de datos."""
from typing import Optional
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
import io

from app.database import get_db
from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor
from app.models.covenant import Covenant, CovenantTracking
from app.models.user import User
from app.security import get_current_user
from app.services.covenant_service import CovenantService
from app.services.report_generator import ReportGenerator

router = APIRouter(prefix="/reports", tags=["Reportes"])


@router.get("/portfolio-summary")
def get_portfolio_summary(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resumen agregado del portafolio para una fecha."""
    if period_date is None:
        period_date = date.today()

    # Obtener balances con disbursement + contract + creditor en un solo query (evita N+1)
    balances = (
        db.query(Balance)
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date == period_date,
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
        raise HTTPException(
            status_code=404,
            detail=f"No hay datos disponibles para {period_date}",
        )

    # Agregaciones
    total_outstanding_usd = Decimal(0)
    total_outstanding_orig = Decimal(0)
    ifd_outstanding = Decimal(0)
    market_outstanding = Decimal(0)
    total_debt_service = Decimal(0)
    total_principal = Decimal(0)
    total_interest = Decimal(0)

    weighted_spread = Decimal(0)
    weighted_term = Decimal(0)
    total_weight = Decimal(0)

    disbursement_count = set()
    contract_count = set()

    for bal in balances:
        disb = bal.disbursement

        disbursement_count.add(disb.id)
        contract_count.add(disb.contract_id)

        total_outstanding_usd += bal.outstanding_usd
        total_outstanding_orig += bal.outstanding_original
        total_debt_service += bal.debt_service_usd or Decimal(0)
        total_principal += bal.amortization_usd or Decimal(0)
        total_interest += bal.interest_usd or Decimal(0)

        # Categorizar por tipo de acreedor (consistente con dashboard)
        creditor_type = disb.contract.creditor.creditor_type if disb.contract and disb.contract.creditor else disb.excel_sheet
        if creditor_type == "IFD":
            ifd_outstanding += bal.outstanding_usd
        elif creditor_type in ("MERCADO", "MARKET"):
            market_outstanding += bal.outstanding_usd

        # Ponderadores
        if bal.outstanding_usd > 0:
            if bal.spread_bps:
                weighted_spread += bal.spread_bps * bal.outstanding_usd
            if bal.residual_term_years:
                weighted_term += bal.residual_term_years * bal.outstanding_usd
            total_weight += bal.outstanding_usd

    avg_spread = (
        weighted_spread / total_weight if total_weight > 0 else Decimal(0)
    )
    avg_term = (
        weighted_term / total_weight if total_weight > 0 else Decimal(0)
    )

    # Ceiling utilization - read from system config
    from app.models.config import SystemConfig
    ceiling_row = db.query(SystemConfig).filter(SystemConfig.key == "debt_ceiling_usd_mm").first()
    ceiling_value = Decimal(str(ceiling_row.value)) if ceiling_row else Decimal(2500)
    ceiling_pct = (total_outstanding_usd / ceiling_value) * Decimal(100) if ceiling_value > 0 else Decimal(0)

    return {
        "period_date": period_date,
        "total_outstanding_usd": float(total_outstanding_usd),
        "total_outstanding_original": float(total_outstanding_orig),
        "ifd_outstanding_usd": float(ifd_outstanding),
        "market_outstanding_usd": float(market_outstanding),
        "weighted_avg_spread_bps": float(avg_spread),
        "weighted_avg_term_years": float(avg_term),
        "debt_service_usd": float(total_debt_service),
        "principal_usd": float(total_principal),
        "interest_usd": float(total_interest),
        "disbursement_count": len(disbursement_count),
        "contract_count": len(contract_count),
        "ceiling_utilization_pct": float(ceiling_pct),
        "ceiling_status": "VERDE" if ceiling_pct <= 80 else (
            "AMARILLO" if ceiling_pct <= 90 else (
                "NARANJA" if ceiling_pct <= 100 else "ROJO"
            )
        ),
    }


@router.get("/monthly-trend")
def get_monthly_trend(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Serie de tiempo mensual de métricas clave del portafolio."""
    from sqlalchemy import func

    rows = (
        db.query(
            Balance.period_date,
            func.sum(Balance.outstanding_usd).label("outstanding_usd"),
            func.sum(func.coalesce(Balance.debt_service_usd, 0)).label("debt_service_usd"),
            func.sum(func.coalesce(Balance.amortization_usd, 0)).label("principal_usd"),
            func.sum(func.coalesce(Balance.interest_usd, 0)).label("interest_usd"),
        )
        .filter(
            Balance.period_date >= from_date,
            Balance.period_date <= to_date,
        )
        .group_by(Balance.period_date)
        .order_by(Balance.period_date)
        .all()
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No hay datos entre {from_date} y {to_date}",
        )

    response = [
        {
            "period_date": row.period_date,
            "outstanding_usd": float(row.outstanding_usd),
            "debt_service_usd": float(row.debt_service_usd),
            "principal_usd": float(row.principal_usd),
            "interest_usd": float(row.interest_usd),
        }
        for row in rows
    ]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "data": response,
    }


@router.get("/covenant-compliance")
def get_covenant_compliance(
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Status de compliance de todos los covenants."""
    if period_date is None:
        period_date = date.today()

    results = CovenantService.batch_evaluate_covenants(db, period_date)

    summary = {
        "periodo_date": period_date,
        "total_covenants": len(results),
        "green": 0,
        "yellow": 0,
        "orange": 0,
        "red": 0,
        "gray": 0,
        "covenants": [],
    }

    for covenant_id, status_data in results.items():
        covenant = status_data["covenant"]
        traffic_light = status_data["traffic_light"]

        if traffic_light == "VERDE":
            summary["green"] += 1
        elif traffic_light == "AMARILLO":
            summary["yellow"] += 1
        elif traffic_light == "NARANJA":
            summary["orange"] += 1
        elif traffic_light == "ROJO":
            summary["red"] += 1
        else:
            summary["gray"] += 1

        summary["covenants"].append({
            "covenant_id": covenant.id,
            "name": covenant.name,
            "type": covenant.covenant_type,
            "current_value": float(status_data.get("current_value") or 0),
            "limit_value": float(covenant.limit_value),
            "utilization_pct": float(status_data.get("utilization_pct") or 0),
            "status": status_data["status"],
            "traffic_light": traffic_light,
        })

    return summary


@router.get("/disbursement-detail")
def get_disbursement_detail(
    period_date: date = Query(...),
    excel_sheet: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Detalle de cada desembolso en una fecha."""
    # Single JOIN query to avoid N+1 (disbursement + contract + creditor per balance)
    q = (
        db.query(Balance, Disbursement, Contract, Creditor)
        .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        .join(Contract, Disbursement.contract_id == Contract.id)
        .join(Creditor, Contract.creditor_id == Creditor.id)
        .filter(
            Balance.period_date == period_date,
            Disbursement.status == "DESEMBOLSADO",
        )
    )

    if excel_sheet:
        q = q.filter(Disbursement.excel_sheet == excel_sheet)

    rows = q.all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No hay datos para {period_date}",
        )

    disbursements = []
    for bal, disb, contract, creditor in rows:
        disbursements.append({
            "disbursement_id": disb.id,
            "disbursement_code": disb.disbursement_code,
            "disbursement_name": disb.disbursement_name,
            "creditor": creditor.name if creditor else "N/A",
            "contract_code": contract.contract_code if contract else "N/A",
            "outstanding_usd": float(bal.outstanding_usd),
            "outstanding_original": float(bal.outstanding_original),
            "maturity_date": disb.maturity_date,
            "spread_bps": float(bal.spread_bps) if bal.spread_bps else None,
            "residual_term_years": float(bal.residual_term_years) if bal.residual_term_years else None,
            "debt_service_usd": float(bal.debt_service_usd or 0),
            "principal_usd": float(bal.amortization_usd or 0),
            "interest_usd": float(bal.interest_usd or 0),
            "excel_sheet": disb.excel_sheet,
        })

    return {
        "period_date": period_date,
        "excel_sheet_filter": excel_sheet,
        "disbursement_count": len(disbursements),
        "disbursements": disbursements,
    }


@router.post("/export-csv")
def export_portfolio_csv(
    period_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Exporta el portafolio en formato CSV."""
    # En producción, generar y descargar archivo CSV
    detail = get_disbursement_detail(period_date, None, db, user)

    return {
        "message": "CSV export ready",
        "data": detail,
        "format": "csv",
        "filename": f"portfolio_{period_date}.csv",
    }


@router.post("/export")
def export_report(
    report_type: str = Query(..., description="portfolio, payments, maturity, covenants"),
    format: str = Query(..., description="csv, xlsx, pdf"),
    period_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export a report in CSV, XLSX, or PDF format."""
    valid_types = ("portfolio", "payments", "maturity", "covenants")
    if report_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid report_type. Must be one of: {', '.join(valid_types)}",
        )

    valid_formats = ("csv", "xlsx", "pdf")
    if format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format. Must be one of: {', '.join(valid_formats)}",
        )

    if period_date is None:
        period_date = date.today()

    filename_base = f"{report_type}_{period_date.isoformat()}"

    if format == "csv":
        title, headers, rows = ReportGenerator._get_report_data(db, report_type, period_date)
        data_dicts = [dict(zip(headers, row)) for row in rows]
        csv_content = ReportGenerator.generate_csv(data_dicts, headers)
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )

    elif format == "xlsx":
        xlsx_bytes = ReportGenerator.generate_xlsx(db, report_type, period_date)
        return StreamingResponse(
            io.BytesIO(xlsx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
        )

    elif format == "pdf":
        pdf_bytes = ReportGenerator.generate_pdf(db, report_type, period_date)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.pdf"'},
        )
