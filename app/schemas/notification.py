"""Pydantic schemas for notifications."""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel


Severity = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]
EntityType = Literal["CONTRACT", "DISBURSEMENT", "COVENANT", "PAYMENT", "SCENARIO"]


class NotificationResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    title: str
    message: Optional[str] = None
    severity: str = "INFO"  # Keep str for response to handle any DB value
    source: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    is_read: bool = False
    read_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class NotificationCreate(BaseModel):
    user_id: Optional[int] = None
    title: str
    message: Optional[str] = None
    severity: Severity = "INFO"
    source: Optional[str] = None
    entity_type: Optional[EntityType] = None
    entity_id: Optional[int] = None


class UnreadCountResponse(BaseModel):
    count: int
