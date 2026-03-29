"""Celery application configuration."""
from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "sistema_endeudamiento",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/La_Paz",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "recalculate-balances-nightly": {
        "task": "app.tasks.recalculate.recalculate_balances",
        "schedule": crontab(hour=2, minute=0),
    },
    "update-fx-rates-daily": {
        "task": "app.tasks.fx_update.update_fx_rates",
        "schedule": crontab(hour=8, minute=0),
    },
    "check-covenant-alerts": {
        "task": "app.tasks.alerts.check_covenant_alerts",
        "schedule": crontab(hour="*/6", minute=0),
    },
    "check-upcoming-payments": {
        "task": "app.tasks.alerts.check_upcoming_payments",
        "schedule": crontab(hour=7, minute=0),
    },
}

celery_app.autodiscover_tasks(["app.tasks"])
