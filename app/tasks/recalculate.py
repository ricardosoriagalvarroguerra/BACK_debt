"""Nightly recalculation of balances and materialized views."""
import logging
from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.recalculate.recalculate_balances")
def recalculate_balances():
    """Recalculate projected balances and refresh materialized views."""
    db = SessionLocal()
    try:
        logger.info("Starting nightly balance recalculation...")

        # Refresh all materialized views
        db.execute(text("SELECT refresh_all_materialized_views()"))
        db.commit()

        logger.info("Materialized views refreshed successfully.")

        # Invalidate dashboard cache
        from app.services.cache_service import CacheService
        CacheService.invalidate_pattern("dashboard:*")

        return {"status": "success", "message": "Balances recalculated and views refreshed"}
    except Exception as e:
        db.rollback()
        logger.error(f"Recalculation failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
