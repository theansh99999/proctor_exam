"""
modules/notifications/channels/in_app.py
----------------------------------------
In-App notification channel. Persists notification records in the database.
"""
from typing import Optional, Dict, Any
import json
from sqlalchemy.orm import Session
from time_utils import utc_now
import models
from modules.notifications.channels.base import BaseNotificationChannel, DeliveryResult


class InAppNotificationChannel(BaseNotificationChannel):
    """Channel that persists in-app notifications for authenticated users."""

    def __init__(self, db: Session, organization_id: Optional[int] = None):
        self.db = db
        self.organization_id = organization_id

    @property
    def channel_name(self) -> str:
        return "in_app"

    def deliver(
        self,
        recipient_id: int,
        recipient_email: Optional[str],
        recipient_name: str,
        title: str,
        message: str,
        html_content: Optional[str] = None,
        action_url: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None
    ) -> DeliveryResult:
        try:
            category = "system"
            event_type = "notification"
            if event_metadata:
                category = event_metadata.get("category", "system")
                event_type = event_metadata.get("event_type", "notification")

            meta_json = json.dumps(event_metadata) if event_metadata else None

            notif = models.Notification(
                organization_id=self.organization_id,
                user_id=recipient_id,
                category=category,
                event_type=event_type,
                title=title,
                message=message,
                action_url=action_url,
                notification_metadata=meta_json,
                delivery_status="sent",
                created_at=utc_now()
            )
            self.db.add(notif)
            self.db.flush()

            # Record in metadata so caller knows the created notification ID
            if event_metadata is not None:
                event_metadata["_created_notification_id"] = notif.id

            return DeliveryResult(
                success=True,
                channel="in_app",
                recipient_id=recipient_id,
                delivered_at=utc_now()
            )
        except Exception as e:
            return DeliveryResult(
                success=False,
                channel="in_app",
                recipient_id=recipient_id,
                error_message=str(e),
                retryable=False
            )
