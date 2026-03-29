from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Creditor(Base):
    __tablename__ = "creditors"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    short_name = Column(String(50), nullable=False)
    creditor_type = Column(String(20), nullable=False)  # 'IFD' o 'MERCADO'
    subtype = Column(String(30), nullable=False)
    country = Column(String(3))
    website = Column(String(300))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    contracts = relationship("Contract", back_populates="creditor")
