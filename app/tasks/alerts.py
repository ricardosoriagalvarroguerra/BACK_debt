"""Alert checking tasks - covenants and upcoming payments."""
import logging
from datetime import date
from dateutil.relativedelta import relativedelta

from app.tasks.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.alerts.check_covenant_alerts")
def check_covenant_alerts():
    """Evaluate all active covenants and create notifications for breaches."""
    db = SessionLocal()
    try:
        from app.services.covenant_service import CovenantService
        from app.services.notification_service import NotificationService
        from app.models.covenant import Covenant

        covenants = db.query(Covenant).filter(Covenant.is_active == True).all()
        today = date.today().replace(day=1) - relativedelta(days=1)  # Last day of prev month
        alerts = 0

        for cov in covenants:
            try:
                current_value, cov_status, traffic_light, utilization_pct = CovenantService.evaluate_covenant(db, cov, today)
                if traffic_light in ("NARANJA", "ROJO"):
                    NotificationService.create_notification(
                        db,
                        user_id=None,
                        title=f"Alerta Covenant: {cov.name}",
                        message=f"Estado: {traffic_light} - Utilizacion: {utilization_pct:.1f}%",
                        severity="WARNING" if traffic_light == "NARANJA" else "CRITICAL",
                        source="covenant_check",
                        entity_type="covenant",
                        entity_id=cov.id,
                    )
                    alerts += 1
            except Exception as e:
                logger.error(f"Error evaluating covenant {cov.id}: {e}")

        db.commit()
        return {"status": "success", "alerts_created": alerts}
    except Exception as e:
        db.rollback()
        logger.error(f"Covenant alert check failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.alerts.check_upcoming_payments")
def check_upcoming_payments():
    """Check for payments due in the next 7 and 30 days."""
    db = SessionLocal()
    try:
        from app.models.payment import PaymentSchedule
        from app.models.disbursement import Disbursement
        from app.services.notification_service import NotificationService
        from sqlalchemy import and_

        today = date.today()
        alerts = 0

        # Payments due in next 7 days
        upcoming_7 = (
            db.query(PaymentSchedule)
            .join(Disbursement)
            .filter(
                and_(
                    PaymentSchedule.status == "PROGRAMADO",
                    PaymentSchedule.payment_date >= today,
                    PaymentSchedule.payment_date <= today + relativedelta(days=7),
                )
            )
            .all()
        )

        for p in upcoming_7:
            NotificationService.create_notification(
                db,
                user_id=None,
                title=f"Pago proximo: {p.payment_type}",
                message=f"Pago de {p.amount_usd:,.2f} USD vence el {p.payment_date}",
                severity="WARNING",
                source="payment_check",
                entity_type="payment_schedule",
                entity_id=p.id,
            )
            alerts += 1

        db.commit()
        return {"status": "success", "alerts_created": alerts}
    except Exception as e:
        db.rollback()
        logger.error(f"Payment alert check failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
