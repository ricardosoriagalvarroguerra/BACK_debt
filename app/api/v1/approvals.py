"""Approval workflow endpoints for maker-checker."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.approval import ApprovalRequest
from app.models.user import User
from app.schemas.approval import ApprovalRequestCreate, ApprovalRequestResponse, ApprovalAction
from app.security import get_current_user, require_role

router = APIRouter(prefix="/approvals", tags=["Aprobaciones"])


@router.get("", response_model=list[ApprovalRequestResponse])
def list_approvals(
    status: str = Query("PENDING"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ApprovalRequest).filter(ApprovalRequest.status == status)
    return q.order_by(ApprovalRequest.requested_at.desc()).all()


@router.post("", response_model=ApprovalRequestResponse)
def create_approval(
    data: ApprovalRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    approval = ApprovalRequest(
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        action=data.action,
        notes=data.notes,
        request_data=data.request_data,
        requested_by=user.id,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/{approval_id}/approve", response_model=ApprovalRequestResponse)
def approve_request(
    approval_id: int,
    action: ApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("ADMIN", "VP_FINANZAS")),
):
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not approval:
        raise HTTPException(404, "Solicitud no encontrada")
    if approval.status != "PENDING":
        raise HTTPException(400, "Solicitud ya fue procesada")

    approval.status = "APPROVED"
    approval.approved_by = user.id
    approval.resolved_at = datetime.now(timezone.utc)
    if action.notes:
        approval.notes = (approval.notes or "") + f"\nAprobacion: {action.notes}"
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/{approval_id}/reject", response_model=ApprovalRequestResponse)
def reject_request(
    approval_id: int,
    action: ApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("ADMIN", "VP_FINANZAS")),
):
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not approval:
        raise HTTPException(404, "Solicitud no encontrada")
    if approval.status != "PENDING":
        raise HTTPException(400, "Solicitud ya fue procesada")

    approval.status = "REJECTED"
    approval.approved_by = user.id
    approval.resolved_at = datetime.now(timezone.utc)
    if action.notes:
        approval.notes = (approval.notes or "") + f"\nRechazo: {action.notes}"
    db.commit()
    db.refresh(approval)
    return approval
