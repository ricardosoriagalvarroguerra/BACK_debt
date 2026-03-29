"""Schemas para covenants."""
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Literal


CovenantType = Literal["TECHO_DEUDA", "PLAZO_PROMEDIO", "SPREAD_PROMEDIO", "CONCENTRACION", "RATIO_SERVICIO"]
CovenantUnit = Literal["USD_MM", "ANOS", "BPS", "PCT", "RATIO"]
CovenantStatus = Literal["CUMPLE", "ADVERTENCIA", "INCUMPLE", "SIN_DATOS", "CUMPLIMIENTO"]
TrafficLight = Literal["VERDE", "AMARILLO", "NARANJA", "ROJO", "GRIS"]


class CovenantResponse(BaseModel):
    id: int
    name: str
    covenant_type: str  # Keep str for response to handle any DB value
    description: Optional[str] = None
    limit_value: Decimal
    warning_pct: Optional[Decimal] = None
    unit: str
    green_max: Optional[Decimal] = None
    yellow_max: Optional[Decimal] = None
    orange_max: Optional[Decimal] = None
    source: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class CovenantTrackingResponse(BaseModel):
    id: int
    covenant_id: int
    period_date: date
    current_value: Decimal
    limit_value: Decimal
    utilization_pct: Optional[Decimal] = None
    status: CovenantStatus
    notes: Optional[str] = None
    calculated_at: datetime

    model_config = {"from_attributes": True}


class CovenantStatusResponse(BaseModel):
    covenant: CovenantResponse
    current_value: Optional[Decimal] = None
    utilization_pct: Optional[Decimal] = None
    status: CovenantStatus = "SIN_DATOS"
    traffic_light: TrafficLight = "GRIS"
    history: List[CovenantTrackingResponse] = []
