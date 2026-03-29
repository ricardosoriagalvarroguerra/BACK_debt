from sqlalchemy import Column, Integer, String, Numeric, Boolean, Text, Date, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True)
    creditor_id = Column(Integer, ForeignKey("creditors.id"), nullable=False)
    contract_code = Column(String(50), unique=True, nullable=False)
    contract_name = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="VIGENTE")

    # Montos
    approved_amount = Column(Numeric(18, 6), nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    approved_amount_usd = Column(Numeric(18, 6))

    # Fechas
    approval_date = Column(Date)
    signing_date = Column(Date)
    effective_date = Column(Date)
    maturity_date = Column(Date, nullable=False)
    grace_period_months = Column(Integer, default=0)

    # Condiciones financieras
    amortization_type = Column(String(20), nullable=False, default="BULLET")
    interest_rate_type = Column(String(20), nullable=False, default="VARIABLE")
    base_rate = Column(String(20), default="SOFR")
    spread_bps = Column(Numeric(10, 4), nullable=False)
    all_in_cost_bps = Column(Numeric(10, 4))
    commitment_fee_bps = Column(Numeric(10, 4), default=0)

    # Frecuencias
    amort_frequency = Column(String(20))
    interest_frequency = Column(String(20))
    amort_start_date = Column(Date)

    # Info adicional
    purpose = Column(Text)
    isin_code = Column(String(20))
    arranger = Column(String(100))
    listing_exchange = Column(String(100))
    documents_path = Column(Text)
    notes = Column(Text)

    # Metadata
    created_by = Column(Integer, ForeignKey("users.id"))
    approved_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    creditor = relationship("Creditor", back_populates="contracts")
    currency = relationship("Currency")
    disbursements = relationship("Disbursement", back_populates="contract", order_by="Disbursement.disbursement_number")
