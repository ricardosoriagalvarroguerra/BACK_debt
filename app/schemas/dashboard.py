"""Schemas para los endpoints del dashboard y metricas consolidadas."""
from pydantic import BaseModel
from datetime import date
from decimal import Decimal
from typing import Optional, List


class PortfolioSummary(BaseModel):
    """Resumen ejecutivo del portafolio (replica filas resumen del Excel)."""
    period_date: date
    total_outstanding_usd: Decimal
    ifd_outstanding_usd: Decimal
    market_outstanding_usd: Decimal
    weighted_avg_spread_bps: Decimal
    weighted_avg_term_years: Decimal
    ifd_spread_bps: Optional[Decimal] = None
    market_spread_bps: Optional[Decimal] = None
    ifd_term_years: Optional[Decimal] = None
    market_term_years: Optional[Decimal] = None
    total_instruments: int
    ifd_instruments: int
    market_instruments: int


class DebtCeilingStatus(BaseModel):
    """Estado del tope de endeudamiento con semaforo."""
    total_outstanding_usd: Decimal
    ceiling_limit_usd: Decimal
    utilization_pct: Decimal
    status: str           # BAJO, MODERADO, ALTO, CRITICO, INCUMPLIMIENTO
    traffic_light: str    # VERDE, AMARILLO, NARANJA, ROJO
    available_capacity_usd: Decimal


class TimeSeriesPoint(BaseModel):
    """Un punto en la serie temporal mensual."""
    period_date: date
    outstanding_usd: Decimal
    spread_bps: Optional[Decimal] = None
    term_years: Optional[Decimal] = None
    amortization_usd: Optional[Decimal] = None
    is_projected: bool = False


class TimeSeriesResponse(BaseModel):
    """Series temporales completas por tipo."""
    ifd: List[TimeSeriesPoint]
    market: List[TimeSeriesPoint]
    total: List[TimeSeriesPoint]


class MaturityProfileItem(BaseModel):
    """Un año del muro de vencimientos."""
    year: int
    creditor_type: str
    creditor_name: str
    instrument_count: int
    total_amount_usd: Decimal
    avg_spread_bps: Optional[Decimal] = None


class CompositionItem(BaseModel):
    """Composicion por acreedor."""
    creditor_type: str
    creditor_code: str
    creditor_name: str
    currency_code: str
    instrument_count: int
    total_outstanding_usd: Decimal
    pct_of_total: Decimal


class TopInstrument(BaseModel):
    """Un instrumento del top N."""
    disbursement_code: str
    disbursement_name: str
    creditor_name: str
    outstanding_usd: Decimal
    spread_bps: Optional[Decimal] = None
    residual_term_years: Optional[Decimal] = None
    creditor_type: str


class ContractingProfileItem(BaseModel):
    """Spread PP y Plazo PP de contratación por año y tipo de acreedor."""
    year: int
    creditor_type: str
    wavg_spread_bps: Optional[Decimal] = None
    wavg_tenor_years: Optional[Decimal] = None
    total_amount_usd: Decimal
    instrument_count: int


class InterestCostYear(BaseModel):
    """Costo de deuda por ano."""
    year: int
    interest_usd: Decimal
    principal_usd: Decimal
    debt_service_usd: Decimal
    wavg_spread_bps: Optional[Decimal] = None
    avg_outstanding_usd: Decimal
    instrument_count: int
    is_projected: bool


class RiskSegment(BaseModel):
    """Un segmento dentro de una dimensión de riesgo."""
    label: str
    amount_usd: Decimal
    pct: Decimal
    instrument_count: int


class RiskProfileResponse(BaseModel):
    """Perfil de riesgo estructural del portafolio."""
    period_date: date
    currency_exposure: List[RiskSegment]
    rate_type: List[RiskSegment]
    amortization_type: List[RiskSegment]
    residual_term: List[RiskSegment]
