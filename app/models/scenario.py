from sqlalchemy import Column, Integer, BigInteger, String, Numeric, Boolean, Text, Date, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(String(20), default="BORRADOR")
    is_base = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    approved_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    assumptions = relationship("ScenarioAssumption", back_populates="scenario", cascade="all, delete-orphan", order_by="ScenarioAssumption.assumption_order")


class ScenarioAssumption(Base):
    __tablename__ = "scenario_assumptions"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    assumption_order = Column(Integer, nullable=False, default=1)
    assumption_type = Column(String(50), nullable=False)

    scenario = relationship("Scenario", back_populates="assumptions")
    description = Column(String(500), nullable=False)
    hypothetical_creditor_id = Column(Integer, ForeignKey("creditors.id"))
    hypothetical_amount_usd = Column(Numeric(18, 6))
    hypothetical_currency_id = Column(Integer, ForeignKey("currencies.id"))
    hypothetical_amount_original = Column(Numeric(18, 6))
    hypothetical_start_date = Column(Date)
    hypothetical_end_date = Column(Date)
    hypothetical_spread_bps = Column(Numeric(10, 4))
    hypothetical_amort_type = Column(Enum('BULLET', 'AMORTIZABLE', 'REVOLVING', name='amortization_type', create_type=False))
    rate_shock_bps = Column(Numeric(10, 4))
    fx_shock_pct = Column(Numeric(10, 4))
    fx_currency_id = Column(Integer, ForeignKey("currencies.id"))
    parameters = Column(JSONB)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class ScenarioResult(Base):
    __tablename__ = "scenario_results"

    id = Column(BigInteger, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    period_date = Column(Date, nullable=False)
    total_outstanding_usd = Column(Numeric(18, 6), nullable=False)
    ifd_outstanding_usd = Column(Numeric(18, 6))
    market_outstanding_usd = Column(Numeric(18, 6))
    hypothetical_usd = Column(Numeric(18, 6), default=0)
    weighted_avg_spread_bps = Column(Numeric(10, 4))
    weighted_avg_term_years = Column(Numeric(10, 6))
    debt_service_usd = Column(Numeric(18, 6))
    principal_usd = Column(Numeric(18, 6))
    interest_usd = Column(Numeric(18, 6))
    ceiling_utilization_pct = Column(Numeric(5, 2))
    ceiling_status = Column(String(20))
    calculated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
