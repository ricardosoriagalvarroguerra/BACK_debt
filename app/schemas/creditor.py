from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal


CreditorType = Literal["IFD", "MERCADO"]


class CreditorBase(BaseModel):
    code: str
    name: str
    short_name: str
    creditor_type: CreditorType
    subtype: str
    country: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None


class CreditorCreate(CreditorBase):
    pass


class CreditorUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CreditorResponse(CreditorBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
