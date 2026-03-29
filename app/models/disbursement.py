from sqlalchemy import Column, Integer, String, Numeric, Text, Date, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Disbursement(Base):
    __tablename__ = "disbursements"

    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    disbursement_number = Column(Integer, nullable=False)
    disbursement_code = Column(String(80), unique=True, nullable=False)
    disbursement_name = Column(String(200), nullable=False)

    # Montos
    amount_original = Column(Numeric(18, 6), nullable=False)
    amount_usd = Column(Numeric(18, 6), nullable=False)
    exchange_rate = Column(Numeric(18, 8))

    # Fechas
    request_date = Column(Date)
    disbursement_date = Column(Date, nullable=False)
    maturity_date = Column(Date, nullable=False)

    # Override de condiciones
    spread_bps_override = Column(Numeric(10, 4))
    interest_rate_type_override = Column(String(20))
    grace_period_months = Column(Integer)

    # Estado
    status = Column(String(20), nullable=False, default="DESEMBOLSADO")

    # Trazabilidad Excel
    excel_sheet = Column(String(50))
    excel_row = Column(Integer)

    # Metadata
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    contract = relationship("Contract", back_populates="disbursements")
    balances = relationship("Balance", back_populates="disbursement", order_by="Balance.period_date")

    @property
    def effective_spread_bps(self):
        """Spread efectivo: override si existe, sino hereda del contrato."""
        if self.spread_bps_override is not None:
            return self.spread_bps_override
        return self.contract.spread_bps if self.contract else None
