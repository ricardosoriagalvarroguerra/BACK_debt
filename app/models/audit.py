from sqlalchemy import Column, Integer, BigInteger, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB, INET
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user_email = Column(String(200))
    action = Column(String(20), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer)
    old_values = Column(JSONB)
    new_values = Column(JSONB)
    ip_address = Column(INET)
    user_agent = Column(Text)
    description = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
