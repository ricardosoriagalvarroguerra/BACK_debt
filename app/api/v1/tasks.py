"""Manual task trigger endpoints."""
from fastapi import APIRouter, Depends
from app.security import require_role

router = APIRouter(prefix="/tasks", tags=["Tareas"])


@router.post("/recalculate")
def trigger_recalculate(user=Depends(require_role("ADMIN", "VP_FINANZAS"))):
    from app.tasks.recalculate import recalculate_balances
    task = recalculate_balances.delay()
    return {"task_id": task.id, "status": "queued"}


@router.post("/fx-update")
def trigger_fx_update(user=Depends(require_role("ADMIN", "VP_FINANZAS"))):
    from app.tasks.fx_update import update_fx_rates
    task = update_fx_rates.delay()
    return {"task_id": task.id, "status": "queued"}


@router.post("/check-alerts")
def trigger_check_alerts(user=Depends(require_role("ADMIN", "VP_FINANZAS"))):
    from app.tasks.alerts import check_covenant_alerts, check_upcoming_payments
    t1 = check_covenant_alerts.delay()
    t2 = check_upcoming_payments.delay()
    return {"tasks": [t1.id, t2.id], "status": "queued"}
