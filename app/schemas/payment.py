"""Schemas para payment schedules."""
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Literal


PaymentType = Literal["PRINCIPAL", "INTEREST", "COMMITMENT_FEE"]
PaymentStatus = Literal["PROGRAMADO", "CONFIRMADO", "EJECUTADO", "VENCIDO", "CANCELADO", "PAGADO"]


class PaymentBase(BaseModel):
    disbursement_id: int
    payment_type: PaymentType
    payment_date: date
    amount_original: Decimal
    amount_usd: Optional[Decimal] = None
    status: PaymentStatus = "PROGRAMADO"
    notes: Optional[str] = None


class PaymentCreate(PaymentBase):
    pass


class PaymentUpdate(BaseModel):
    payment_type: Optional[PaymentType] = None
    payment_date: Optional[date] = None
    amount_original: Optional[Decimal] = None
    amount_usd: Optional[Decimal] = None
    status: Optional[PaymentStatus] = None
    actual_payment_date: Optional[date] = None
    actual_amount_original: Optional[Decimal] = None
    actual_amount_usd: Optional[Decimal] = None
    notes: Optional[str] = None


class PaymentResponse(PaymentBase):
    id: int
    actual_payment_date: Optional[date] = None
    actual_amount_original: Optional[Decimal] = None
    actual_amount_usd: Optional[Decimal] = None
    exchange_rate_used: Optional[Decimal] = None
    created_at: datetime

    model_config = {"from_attributes": True}
