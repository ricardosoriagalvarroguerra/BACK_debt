"""Schemas para scenarios y simulaciones."""
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Literal


AssumptionType = Literal["NUEVO_DESEMBOLSO", "RATE_SHOCK", "FX_SHOCK", "PREPAGO"]
ScenarioStatus = Literal["BORRADOR", "SIMULADO", "APROBADO", "ARCHIVADO"]
AmortType = Literal["BULLET", "AMORTIZABLE", "REVOLVING"]
CeilingStatus = Literal["VERDE", "AMARILLO", "NARANJA", "ROJO"]


class ScenarioAssumptionCreate(BaseModel):
    assumption_order: int = 1
    assumption_type: AssumptionType
    description: str
    hypothetical_creditor_id: Optional[int] = None
    hypothetical_amount_usd: Optional[Decimal] = None
    hypothetical_currency_id: Optional[int] = None
    hypothetical_amount_original: Optional[Decimal] = None
    hypothetical_start_date: Optional[date] = None
    hypothetical_end_date: Optional[date] = None
    hypothetical_spread_bps: Optional[Decimal] = None
    hypothetical_amort_type: Optional[AmortType] = None
    rate_shock_bps: Optional[Decimal] = None
    fx_shock_pct: Optional[Decimal] = None
    fx_currency_id: Optional[int] = None
    parameters: Optional[dict] = None


class ScenarioAssumptionResponse(ScenarioAssumptionCreate):
    id: int
    scenario_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ScenarioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_base: bool = False
    assumptions: List[ScenarioAssumptionCreate] = []


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ScenarioStatus] = None


class ScenarioResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    is_base: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ScenarioWithAssumptions(ScenarioResponse):
    assumptions: List[ScenarioAssumptionResponse] = []


class ScenarioResultResponse(BaseModel):
    period_date: date
    total_outstanding_usd: Decimal
    ifd_outstanding_usd: Optional[Decimal] = None
    market_outstanding_usd: Optional[Decimal] = None
    hypothetical_usd: Optional[Decimal] = None
    weighted_avg_spread_bps: Optional[Decimal] = None
    weighted_avg_term_years: Optional[Decimal] = None
    debt_service_usd: Optional[Decimal] = None
    principal_usd: Optional[Decimal] = None
    interest_usd: Optional[Decimal] = None
    ceiling_utilization_pct: Optional[Decimal] = None
    ceiling_status: Optional[CeilingStatus] = None

    model_config = {"from_attributes": True}


class ScenarioCompareResponse(BaseModel):
    scenario_id: int
    scenario_name: str
    results: List[ScenarioResultResponse]
