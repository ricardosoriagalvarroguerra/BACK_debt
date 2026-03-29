from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Literal


DisbursementStatus = Literal["DESEMBOLSADO", "PENDIENTE", "CANCELADO", "PAGADO"]


class DisbursementBase(BaseModel):
    contract_id: int
    disbursement_number: int
    disbursement_code: str
    disbursement_name: str
    amount_original: Decimal
    amount_usd: Decimal
    exchange_rate: Optional[Decimal] = None
    disbursement_date: date
    maturity_date: date
    spread_bps_override: Optional[Decimal] = None
    grace_period_months: Optional[int] = None
    status: DisbursementStatus = "DESEMBOLSADO"
    excel_sheet: Optional[str] = None
    excel_row: Optional[int] = None
    notes: Optional[str] = None


class DisbursementCreate(DisbursementBase):
    pass


class DisbursementResponse(DisbursementBase):
    id: int
    effective_spread_bps: Optional[Decimal] = None
    contract_spread_bps: Optional[Decimal] = None
    created_at: datetime

    model_config = {"from_attributes": True}
