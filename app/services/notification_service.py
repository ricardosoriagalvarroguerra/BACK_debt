"""Notification service for creating and managing notifications."""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.notification import Notification


class NotificationService:

    @staticmethod
    def create_notification(
        db: Session,
        user_id: Optional[int],
        title: str,
        message: str,
        severity: str = "INFO",
        source: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
    ) -> Notification:
        notif = Notification(
            user_id=user_id,
            title=title,
            message=message,
            severity=severity,
            source=source,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        db.add(notif)
        return notif

    @staticmethod
    def get_unread_count(db: Session, user_id: Optional[int] = None) -> int:
        q = db.query(Notification).filter(Notification.is_read == False)
        if user_id:
            q = q.filter((Notification.user_id == user_id) | (Notification.user_id == None))
        return q.count()

    @staticmethod
    def mark_read(db: Session, notification_id: int) -> bool:
        from datetime import datetime, timezone
        notif = db.query(Notification).filter(Notification.id == notification_id).first()
        if notif:
            notif.is_read = True
            notif.read_at = datetime.now(timezone.utc)
            return True
        return False

    @staticmethod
    def mark_all_read(db: Session, user_id: Optional[int] = None):
        from datetime import datetime, timezone
        q = db.query(Notification).filter(Notification.is_read == False)
        if user_id:
            q = q.filter((Notification.user_id == user_id) | (Notification.user_id == None))
        q.update({"is_read": True, "read_at": datetime.now(timezone.utc)}, synchronize_session=False)
