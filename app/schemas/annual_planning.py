"""Schemas for Annual Debt Planning Wizard."""
from datetime import date
from decimal import Decimal
from typing import List, Optional, Literal
from pydantic import BaseModel


class MaturityItem(BaseModel):
    """An instrument maturing in the selected year."""
    disbursement_id: int
    disbursement_code: str
    disbursement_name: str
    creditor_code: str
    creditor_name: str
    creditor_type: str  # IFD or MERCADO
    contract_code: str
    amount_usd: float
    maturity_date: date
    spread_bps: float | None
    currency_code: str
    amortization_type: str


class MaturityDecision(BaseModel):
    """Decision for a maturing instrument."""
    disbursement_id: int
    action: Literal["REFINANCIAR", "VENCER", "OMITIR"]
    # Refinancing parameters (only when action=REFINANCIAR)
    new_amount: float | None = None
    new_spread_bps: float | None = None
    new_maturity_date: date | None = None
    new_amort_type: str | None = None  # BULLET, AMORTIZABLE
    new_currency: str | None = None
    new_description: str | None = None


class AdditionalOperation(BaseModel):
    """A new market emission to add to the plan."""
    description: str
    amount_usd: float
    spread_bps: float
    currency: str = "USD"
    start_date: date | None = None
    maturity_date: date
    amort_type: str = "BULLET"
    creditor_type: str = "MERCADO"


class KPISnapshot(BaseModel):
    """Current vs projected KPIs."""
    current_outstanding_usd: float
    projected_outstanding_usd: float
    current_ceiling_pct: float
    projected_ceiling_pct: float
    current_spread_pp: float
    projected_spread_pp: float
    current_term_pp: float
    projected_term_pp: float
    current_debt_service: float
    projected_debt_service: float
    ceiling_limit_usd: float


class TimelinePoint(BaseModel):
    """A point in the projection timeline."""
    period_date: str
    outstanding_usd: float
    ceiling_pct: float


class QuickSimulateRequest(BaseModel):
    """Request for quick simulation."""
    year: int
    decisions: List[MaturityDecision] = []
    additional_operations: List[AdditionalOperation] = []


class QuickSimulateResponse(BaseModel):
    """Response with KPIs and timeline."""
    kpi: KPISnapshot
    timeline: List[TimelinePoint]


class SavePlanRequest(BaseModel):
    """Save the plan as a scenario."""
    year: int
    name: str | None = None
    description: str | None = None
    decisions: List[MaturityDecision] = []
    additional_operations: List[AdditionalOperation] = []
