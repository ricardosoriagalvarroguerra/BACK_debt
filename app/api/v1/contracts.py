"""CRUD de contratos."""
import logging
from typing import List, Optional
from datetime import datetime, date, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models.contract import Contract
from app.models.disbursement import Disbursement
from app.models.user import User
from app.schemas.contract import ContractCreate, ContractResponse, ContractWithDisbursements
from app.schemas.disbursement import DisbursementResponse
from app.security import get_current_user

logger = logging.getLogger(__name__)


class ContractUpdate(BaseModel):
    contract_name: Optional[str] = None
    status: Optional[str] = None
    spread_bps: Optional[Decimal] = None
    amortization_type: Optional[str] = None
    interest_rate_type: Optional[str] = None
    base_rate: Optional[str] = None
    maturity_date: Optional[date] = None
    purpose: Optional[str] = None
    notes: Optional[str] = None
    arranger: Optional[str] = None
    isin_code: Optional[str] = None


class AddDisbursementRequest(BaseModel):
    amount_usd: Decimal
    amount_original: Optional[Decimal] = None
    exchange_rate: Optional[Decimal] = Decimal("1")
    disbursement_date: Optional[date] = None
    maturity_date: Optional[date] = None
    spread_bps_override: Optional[Decimal] = None
    notes: Optional[str] = None
    excel_sheet: Optional[str] = None

router = APIRouter(prefix="/contracts", tags=["Contratos"])


@router.get("", response_model=List[ContractResponse])
def list_contracts(
    status: Optional[str] = Query(None, description="VIGENTE, VENCIDO, etc."),
    creditor_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista contratos con filtros opcionales y paginación."""
    q = db.query(Contract).options(
        joinedload(Contract.creditor),
        joinedload(Contract.currency),
    )
    if status:
        q = q.filter(Contract.status == status)
    if creditor_id:
        q = q.filter(Contract.creditor_id == creditor_id)
    return q.order_by(Contract.contract_code).offset(skip).limit(limit).all()


@router.get("/{contract_id}", response_model=ContractWithDisbursements)
def get_contract(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Detalle de un contrato con sus desembolsos."""
    contract = (
        db.query(Contract)
        .options(joinedload(Contract.disbursements))
        .filter(Contract.id == contract_id)
        .first()
    )
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    return contract


@router.post("", response_model=ContractResponse, status_code=201)
def create_contract(data: ContractCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Crear nuevo contrato."""
    existing = db.query(Contract).filter(Contract.contract_code == data.contract_code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existe contrato con codigo {data.contract_code}")
    contract = Contract(**data.model_dump())
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@router.put("/{contract_id}", response_model=ContractResponse)
def update_contract(
    contract_id: int,
    data: ContractUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Actualiza un contrato existente."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")

    # Update only provided fields (exclude_unset skips None-by-default fields)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(contract, field, value)

    contract.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(contract)
    return contract


@router.get("/{contract_id}/disbursements", response_model=List[DisbursementResponse])
def get_contract_disbursements(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Lista desembolsos de un contrato."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    return (
        db.query(Disbursement)
        .filter(Disbursement.contract_id == contract_id)
        .order_by(Disbursement.disbursement_number)
        .all()
    )


@router.post("/{contract_id}/disbursements", response_model=DisbursementResponse, status_code=201)
def add_disbursement_to_contract(
    contract_id: int,
    data: AddDisbursementRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Agrega un nuevo desembolso a un contrato existente."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")

    # Auto-generar numero y codigo
    max_num = (
        db.query(func.max(Disbursement.disbursement_number))
        .filter(Disbursement.contract_id == contract_id)
        .scalar() or 0
    )
    next_num = max_num + 1
    disb_code = f"{contract.contract_code}-D{next_num}"

    # Defaults
    disb_date = data.disbursement_date or date.today()
    mat_date = data.maturity_date or contract.maturity_date
    amount_orig = data.amount_original or data.amount_usd

    disbursement = Disbursement(
        contract_id=contract_id,
        disbursement_number=next_num,
        disbursement_code=disb_code,
        disbursement_name=f"{contract.contract_name} - Desembolso {next_num}",
        amount_original=amount_orig,
        amount_usd=data.amount_usd,
        exchange_rate=data.exchange_rate,
        disbursement_date=disb_date,
        maturity_date=mat_date,
        spread_bps_override=data.spread_bps_override,
        status="DESEMBOLSADO",
        excel_sheet=data.excel_sheet,
        notes=data.notes,
    )
    db.add(disbursement)
    db.commit()
    db.refresh(disbursement)

    # Auto-generar pagos y balances
    from app.api.v1.disbursements import _auto_generate_schedule, _enrich_disbursement
    gen_result = _auto_generate_schedule(db, disbursement, contract)
    logger.info(f"Desembolso {disbursement.id} agregado a contrato {contract_id}: {gen_result}")

    db.refresh(disbursement)
    # Reload with contract for enrichment
    disbursement = (
        db.query(Disbursement)
        .options(joinedload(Disbursement.contract))
        .filter(Disbursement.id == disbursement.id)
        .first()
    )
    enriched = _enrich_disbursement(disbursement)
    enriched["generation_result"] = gen_result
    return enriched
