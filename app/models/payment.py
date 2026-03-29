from sqlalchemy import Column, Integer, BigInteger, Numeric, Text, Date, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from app.database import Base


class PaymentSchedule(Base):
    __tablename__ = "payment_schedule"

    id = Column(BigInteger, primary_key=True)
    disbursement_id = Column(Integer, ForeignKey("disbursements.id"), nullable=False)
    payment_type = Column(
        Enum("PRINCIPAL", "INTEREST", "COMMITMENT_FEE", "OTHER_FEE", name="payment_type", create_type=False),
        nullable=False,
    )
    payment_date = Column(Date, nullable=False)
    amount_original = Column(Numeric(18, 6), nullable=False)
    amount_usd = Column(Numeric(18, 6))
    exchange_rate_used = Column(Numeric(18, 8))

    status = Column(
        Enum("PROGRAMADO", "CONFIRMADO", "PAGADO", "VENCIDO", "CANCELADO", name="payment_status", create_type=False),
        nullable=False,
        default="PROGRAMADO",
    )
    actual_payment_date = Column(Date)
    actual_amount_original = Column(Numeric(18, 6))
    actual_amount_usd = Column(Numeric(18, 6))

    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
