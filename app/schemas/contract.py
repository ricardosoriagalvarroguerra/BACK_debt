from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Literal


ContractStatus = Literal["VIGENTE", "VENCIDO", "CANCELADO", "PAGADO"]
AmortizationType = Literal["BULLET", "AMORTIZABLE", "REVOLVING"]
InterestRateType = Literal["FIJA", "VARIABLE"]
BaseRateType = Literal["SOFR", "EURIBOR", "LIBOR", "TIIE", "FIJA"]
FrequencyType = Literal["MENSUAL", "TRIMESTRAL", "SEMESTRAL", "ANUAL", "AL_VENCIMIENTO"]


class ContractBase(BaseModel):
    creditor_id: int
    contract_code: str
    contract_name: str
    status: ContractStatus = "VIGENTE"
    approved_amount: Decimal
    currency_id: int
    approved_amount_usd: Optional[Decimal] = None
    signing_date: Optional[date] = None
    effective_date: Optional[date] = None
    maturity_date: date
    amortization_type: AmortizationType = "BULLET"
    interest_rate_type: InterestRateType = "VARIABLE"
    base_rate: Optional[BaseRateType] = "SOFR"
    spread_bps: Decimal
    grace_period_months: Optional[int] = 0
    amort_frequency: Optional[FrequencyType] = None
    interest_frequency: Optional[FrequencyType] = None
    commitment_fee_bps: Optional[Decimal] = None
    purpose: Optional[str] = None
    notes: Optional[str] = None


class ContractCreate(ContractBase):
    pass


class ContractResponse(ContractBase):
    id: int
    grace_period_months: Optional[int] = 0
    all_in_cost_bps: Optional[Decimal] = None
    commitment_fee_bps: Optional[Decimal] = None
    isin_code: Optional[str] = None
    arranger: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractWithDisbursements(ContractResponse):
    disbursements: List["DisbursementResponse"] = []


# Import at end to avoid circular
from app.schemas.disbursement import DisbursementResponse
ContractWithDisbursements.model_rebuild()
