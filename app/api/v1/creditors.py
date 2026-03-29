"""CRUD de acreedores."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.creditor import Creditor
from app.models.user import User
from app.schemas.creditor import CreditorCreate, CreditorUpdate, CreditorResponse
from app.security import get_current_user

router = APIRouter(prefix="/creditors", tags=["Acreedores"])


@router.get("", response_model=List[CreditorResponse])
def list_creditors(
    creditor_type: Optional[str] = Query(None, description="IFD o MERCADO"),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista todos los acreedores con filtros opcionales."""
    q = db.query(Creditor)
    if creditor_type:
        q = q.filter(Creditor.creditor_type == creditor_type)
    if is_active is not None:
        q = q.filter(Creditor.is_active == is_active)
    return q.order_by(Creditor.creditor_type, Creditor.code).all()


@router.get("/{creditor_id}", response_model=CreditorResponse)
def get_creditor(creditor_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Detalle de un acreedor por ID."""
    creditor = db.query(Creditor).filter(Creditor.id == creditor_id).first()
    if not creditor:
        raise HTTPException(status_code=404, detail="Acreedor no encontrado")
    return creditor


@router.post("", response_model=CreditorResponse, status_code=201)
def create_creditor(data: CreditorCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Crear nuevo acreedor."""
    existing = db.query(Creditor).filter(Creditor.code == data.code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existe acreedor con codigo {data.code}")
    creditor = Creditor(**data.model_dump())
    db.add(creditor)
    db.commit()
    db.refresh(creditor)
    return creditor


@router.put("/{creditor_id}", response_model=CreditorResponse)
def update_creditor(creditor_id: int, data: CreditorUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Actualizar acreedor existente."""
    creditor = db.query(Creditor).filter(Creditor.id == creditor_id).first()
    if not creditor:
        raise HTTPException(status_code=404, detail="Acreedor no encontrado")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(creditor, field, value)
    db.commit()
    db.refresh(creditor)
    return creditor
