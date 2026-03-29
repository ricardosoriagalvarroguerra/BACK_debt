"""Servicio de tipos de cambio."""
from datetime import date
from decimal import Decimal
from typing import Optional, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.currency import Currency


class FxService:
    """Gestión de tipos de cambio para conversión multi-moneda."""

    # Default rates (as of initial migration)
    DEFAULT_RATES: Dict[str, Decimal] = {
        "USD": Decimal("1.0"),
        "EUR": Decimal("1.08"),
        "CHF": Decimal("1.12"),
        "JPY": Decimal("0.0067"),
        "GBP": Decimal("1.27"),
        "INR": Decimal("0.012"),
        "SEK": Decimal("0.095"),
        "NOK": Decimal("0.093"),
        "BRL": Decimal("0.20"),
        "BOB": Decimal("0.145"),
    }

    @staticmethod
    def get_rate(db: Session, currency_code: str, as_of: Optional[date] = None) -> Decimal:
        """Get exchange rate to USD for a currency."""
        if currency_code == "USD":
            return Decimal("1.0")

        # Try from exchange_rates table first
        try:
            from app.models.exchange_rate import ExchangeRate
            from app.models.currency import Currency as Cur
            q = (
                db.query(ExchangeRate.rate_to_usd)
                .join(Cur, ExchangeRate.currency_id == Cur.id)
                .filter(Cur.code == currency_code)
            )
            if as_of:
                q = q.filter(ExchangeRate.rate_date <= as_of)
            q = q.order_by(ExchangeRate.rate_date.desc())
            row = q.first()
            if row and row.rate_to_usd:
                return Decimal(str(row.rate_to_usd))
        except Exception:
            pass

        # Try from system config
        from app.models.config import SystemConfig
        rate_key = f"fx_rate_{currency_code.lower()}"
        config = db.query(SystemConfig).filter(SystemConfig.key == rate_key).first()
        if config:
            try:
                return Decimal(str(config.value))
            except (ValueError, TypeError):
                pass

        # Fallback to defaults
        return FxService.DEFAULT_RATES.get(currency_code, Decimal("1.0"))

    @staticmethod
    def convert_to_usd(
        db: Session,
        amount: Decimal,
        currency_code: str,
        as_of: Optional[date] = None,
    ) -> Decimal:
        """Convert an amount to USD."""
        rate = FxService.get_rate(db, currency_code, as_of)
        return (amount * rate).quantize(Decimal("0.000001"))

    @staticmethod
    def get_all_rates(db: Session) -> Dict[str, float]:
        """Get all current exchange rates in a single query instead of N+1."""
        from app.models.exchange_rate import ExchangeRate

        currencies = db.query(Currency).filter(Currency.is_active == True).all()
        currency_codes = [c.code for c in currencies]

        rates = {}

        # Fetch all latest rates at once using a subquery for max(rate_date) per currency
        if currency_codes:
            # Subquery: max rate_date per currency_id
            latest_dates = (
                db.query(
                    ExchangeRate.currency_id,
                    func.max(ExchangeRate.rate_date).label("max_date"),
                )
                .group_by(ExchangeRate.currency_id)
                .subquery()
            )

            # Join to get the actual rates at the latest dates
            rows = (
                db.query(Currency.code, ExchangeRate.rate_to_usd)
                .join(ExchangeRate, ExchangeRate.currency_id == Currency.id)
                .join(
                    latest_dates,
                    and_(
                        ExchangeRate.currency_id == latest_dates.c.currency_id,
                        ExchangeRate.rate_date == latest_dates.c.max_date,
                    ),
                )
                .filter(Currency.code.in_(currency_codes))
                .all()
            )

            for row in rows:
                rates[row.code] = float(row.rate_to_usd)

        # Fill in any currencies that didn't have exchange_rate records
        for c in currencies:
            if c.code not in rates:
                rates[c.code] = float(FxService.DEFAULT_RATES.get(c.code, Decimal("1.0")))

        return rates

    @staticmethod
    def update_rates(db: Session, rates: Dict[str, float]) -> Dict[str, float]:
        """Bulk update exchange rates."""
        from app.models.config import SystemConfig
        updated = {}
        for code, rate in rates.items():
            key = f"fx_rate_{code.lower()}"
            config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if config:
                config.value = str(rate)
            else:
                config = SystemConfig(key=key, value=str(rate), description=f"Tipo de cambio {code}/USD")
                db.add(config)
            updated[code] = rate
        db.commit()
        return updated
