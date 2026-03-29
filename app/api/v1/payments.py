"""CRUD de payment schedules."""
from typing import List, Optional
from datetime import date, datetime, timezone
from decimal import Decimal
import calendar
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.payment import PaymentSchedule
from app.models.disbursement import Disbursement
from app.models.user import User
from app.schemas.payment import (
    PaymentCreate,
    PaymentUpdate,
    PaymentResponse,
)
from app.security import get_current_user

router = APIRouter(prefix="/payments", tags=["Pagos"])


def _add_months(d: date, months: int) -> date:
    """Add months to a date, clamping to last day of month if needed."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@router.get("", response_model=List[PaymentResponse])
def list_payments(
    disbursement_id: Optional[int] = Query(None),
    payment_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista payment schedules con filtros opcionales y paginación."""
    q = db.query(PaymentSchedule)
    if disbursement_id:
        q = q.filter(PaymentSchedule.disbursement_id == disbursement_id)
    if payment_type:
        q = q.filter(PaymentSchedule.payment_type == payment_type)
    if status:
        q = q.filter(PaymentSchedule.status == status)
    return q.order_by(PaymentSchedule.payment_date).offset(skip).limit(limit).all()


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Detalle de un payment schedule."""
    payment = db.query(PaymentSchedule).filter(PaymentSchedule.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    return payment


@router.post("", response_model=PaymentResponse, status_code=201)
def create_payment(data: PaymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Crear nuevo payment schedule."""
    # Validar desembolso existe
    disb = db.query(Disbursement).filter(Disbursement.id == data.disbursement_id).first()
    if not disb:
        raise HTTPException(status_code=404, detail="Desembolso no encontrado")

    payment = PaymentSchedule(**data.model_dump())
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.put("/{payment_id}", response_model=PaymentResponse)
def update_payment(
    payment_id: int,
    data: PaymentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Actualiza un payment schedule."""
    payment = db.query(PaymentSchedule).filter(PaymentSchedule.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(payment, field, value)

    payment.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(payment)
    return payment


@router.post("/{disbursement_id}/auto-generate", status_code=201)
def auto_generate_payments(
    disbursement_id: int,
    force_regenerate: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Auto-genera un schedule de pagos para un desembolso.

    Crea pagos mensuales de principal e interés según el tipo de amortización.
    """
    disb = db.query(Disbursement).filter(Disbursement.id == disbursement_id).first()
    if not disb:
        raise HTTPException(status_code=404, detail="Desembolso no encontrado")

    contract = disb.contract
    if not contract:
        raise HTTPException(status_code=400, detail="Desembolso sin contrato asociado")

    # Si force_regenerate, eliminar schedules previos
    if force_regenerate:
        db.query(PaymentSchedule).filter(
            PaymentSchedule.disbursement_id == disbursement_id
        ).delete()
        db.commit()

    # Calcular parámetros
    current_date = disb.disbursement_date
    maturity = disb.maturity_date
    amount_usd = disb.amount_usd
    amount_orig = disb.amount_original

    # Frequency (default mensual)
    frequency = contract.interest_frequency or "MENSUAL"

    # Amortización
    amort_type = contract.amortization_type

    created_payments = []

    if amort_type == "BULLET":
        # BULLET: solo interés hasta vencimiento, luego principal
        while current_date < maturity:
            # Pago de interés
            interest_payment = PaymentSchedule(
                disbursement_id=disbursement_id,
                payment_type="INTEREST",
                payment_date=current_date,
                amount_original=Decimal(0),  # Simplificado
                amount_usd=Decimal(0),  # Calculado luego
                status="PROGRAMADO",
            )
            db.add(interest_payment)
            created_payments.append(interest_payment)

            # Añadir mes
            if frequency == "MENSUAL":
                current_date = _add_months(current_date, 1)
            else:
                current_date = _add_months(current_date, 3)

        # Principal al vencimiento
        principal_payment = PaymentSchedule(
            disbursement_id=disbursement_id,
            payment_type="PRINCIPAL",
            payment_date=maturity,
            amount_original=amount_orig,
            amount_usd=amount_usd,
            status="PROGRAMADO",
        )
        db.add(principal_payment)
        created_payments.append(principal_payment)

    elif amort_type == "AMORTIZABLE":
        # AMORTIZABLE: reducción lineal mensual
        months_to_maturity = (maturity.year - disb.disbursement_date.year) * 12 + (
            maturity.month - disb.disbursement_date.month
        )
        monthly_principal = amount_usd / max(months_to_maturity, 1)
        monthly_principal_orig = amount_orig / max(months_to_maturity, 1)

        while current_date <= maturity:
            # Pago de principal
            principal_payment = PaymentSchedule(
                disbursement_id=disbursement_id,
                payment_type="PRINCIPAL",
                payment_date=current_date,
                amount_original=monthly_principal_orig,
                amount_usd=monthly_principal,
                status="PROGRAMADO",
            )
            db.add(principal_payment)
            created_payments.append(principal_payment)

            # Pago de interés
            interest_payment = PaymentSchedule(
                disbursement_id=disbursement_id,
                payment_type="INTEREST",
                payment_date=current_date,
                amount_original=Decimal(0),
                amount_usd=Decimal(0),
                status="PROGRAMADO",
            )
            db.add(interest_payment)
            created_payments.append(interest_payment)

            # Añadir mes
            current_date = _add_months(current_date, 1)

    db.commit()
    return {
        "disbursement_id": disbursement_id,
        "payments_created": len(created_payments),
        "status": "success",
    }
