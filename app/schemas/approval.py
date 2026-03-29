"""Pydantic schemas for approval requests."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ApprovalRequestCreate(BaseModel):
    entity_type: str
    entity_id: int
    action: str
    notes: Optional[str] = None
    request_data: Optional[str] = None


class ApprovalRequestResponse(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    status: str
    requested_by: int
    approved_by: Optional[int] = None
    notes: Optional[str] = None
    request_data: Optional[str] = None
    requested_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApprovalAction(BaseModel):
    notes: Optional[str] = None
