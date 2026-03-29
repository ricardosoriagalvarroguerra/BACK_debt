"""FX rate update task."""
import logging

from app.tasks.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.fx_update.update_fx_rates")
def update_fx_rates():
    """Update exchange rates from configured source."""
    db = SessionLocal()
    try:
        from app.services.fx_service import FxService
        fx = FxService()

        rates = fx.get_all_rates(db)
        logger.info(f"Current FX rates: {len(rates)} currencies tracked")

        return {"status": "success", "currencies": len(rates)}
    except Exception as e:
        logger.error(f"FX update failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
