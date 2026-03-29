"""Notification model - maps to existing notifications table."""
from sqlalchemy import Column, BigInteger, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(200), nullable=False)
    message = Column(Text)
    severity = Column(String(20), default="INFO")  # INFO, WARNING, CRITICAL
    source = Column(String(50))
    entity_type = Column(String(50))
    entity_id = Column(Integer)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
