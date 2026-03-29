"""Exchange rate endpoints."""
from typing import Dict, Optional
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.currency import Currency
from app.models.user import User
from app.security import get_current_user
from app.services.fx_service import FxService

router = APIRouter(prefix="/exchange-rates", tags=["Tipos de Cambio"])

class CurrencyResponse(BaseModel):
    id: int
    code: str
    name: str
    symbol: str | None
    model_config = {"from_attributes": True}

class RatesResponse(BaseModel):
    rates: Dict[str, float]
    as_of: str

class BulkUpdateRequest(BaseModel):
    rates: Dict[str, float]

@router.get("/currencies")
def list_currencies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    currencies = db.query(Currency).filter(Currency.is_active == True).all()
    return [{"id": c.id, "code": c.code, "name": c.name, "symbol": c.symbol} for c in currencies]

@router.get("/rates")
def get_rates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rates = FxService.get_all_rates(db)
    return {"rates": rates, "as_of": date.today().isoformat()}

@router.get("/convert")
def convert(
    amount: float = Query(...),
    from_currency: str = Query(...),
    to_currency: str = Query("USD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from decimal import Decimal
    usd_amount = FxService.convert_to_usd(db, Decimal(str(amount)), from_currency)
    if to_currency != "USD":
        target_rate = FxService.get_rate(db, to_currency)
        result = float(usd_amount / target_rate) if target_rate else float(usd_amount)
    else:
        result = float(usd_amount)
    return {"amount": amount, "from": from_currency, "to": to_currency, "result": round(result, 6)}

@router.post("/rates/bulk-update")
def bulk_update_rates(request: BulkUpdateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    updated = FxService.update_rates(db, request.rates)
    return {"updated": updated, "count": len(updated)}
