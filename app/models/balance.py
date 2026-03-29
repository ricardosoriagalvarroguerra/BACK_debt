from sqlalchemy import Column, Integer, BigInteger, Numeric, Boolean, Date, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Balance(Base):
    __tablename__ = "balances"

    id = Column(BigInteger, primary_key=True)
    disbursement_id = Column(Integer, ForeignKey("disbursements.id"), nullable=False)
    period_date = Column(Date, nullable=False)

    # Saldos
    outstanding_original = Column(Numeric(18, 6), nullable=False)
    outstanding_usd = Column(Numeric(18, 6), nullable=False)
    exchange_rate_used = Column(Numeric(18, 8))

    # Metricas
    residual_term_years = Column(Numeric(10, 6))
    spread_bps = Column(Numeric(10, 4))
    amortization_usd = Column(Numeric(18, 6), default=0)
    interest_usd = Column(Numeric(18, 6), default=0)
    debt_service_usd = Column(Numeric(18, 6), default=0)

    # Control
    is_projected = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    calculation_date = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    disbursement = relationship("Disbursement", back_populates="balances")
