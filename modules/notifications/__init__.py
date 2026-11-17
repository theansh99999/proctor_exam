"""
modules/notifications/__init__.py
---------------------------------
Notification module entry point.
"""
from modules.notifications.service import NotificationService
from modules.notifications.router import router as notification_router

__all__ = [
    "NotificationService",
    "notification_router"
]
