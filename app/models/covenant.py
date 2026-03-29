from sqlalchemy import Column, Integer, BigInteger, String, Numeric, Boolean, Text, Date, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from app.database import Base


class Covenant(Base):
    __tablename__ = "covenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    covenant_type = Column(String(30), nullable=False)
    description = Column(Text)
    limit_value = Column(Numeric(18, 6), nullable=False)
    warning_pct = Column(Numeric(5, 2), default=90)
    unit = Column(String(20), nullable=False)
    green_max = Column(Numeric(18, 6))
    yellow_max = Column(Numeric(18, 6))
    orange_max = Column(Numeric(18, 6))
    source = Column(String(200))
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class CovenantTracking(Base):
    __tablename__ = "covenant_tracking"

    id = Column(BigInteger, primary_key=True)
    covenant_id = Column(Integer, ForeignKey("covenants.id"), nullable=False)
    period_date = Column(Date, nullable=False)
    current_value = Column(Numeric(18, 6), nullable=False)
    limit_value = Column(Numeric(18, 6), nullable=False)
    utilization_pct = Column(Numeric(5, 2))
    status = Column(String(20), nullable=False)
    notes = Column(Text)
    calculated_by = Column(String(50), default="SYSTEM")
    calculated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
