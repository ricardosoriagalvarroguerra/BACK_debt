"""Exchange rate model - maps to existing exchange_rates table."""
from sqlalchemy import Column, Integer, BigInteger, Date, Numeric, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.database import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id = Column(BigInteger, primary_key=True, index=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    rate_date = Column(Date, nullable=False)
    rate_to_usd = Column(Numeric(18, 8), nullable=False)
    rate_from_usd = Column(Numeric(18, 8))
    source = Column(String(50), default="MANUAL")
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
