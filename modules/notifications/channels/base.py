"""
modules/notifications/channels/base.py
--------------------------------------
Base channel contract and delivery result definition.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DeliveryResult:
    success: bool
    channel: str
    recipient_id: int
    error_message: Optional[str] = None
    retryable: bool = False
    delivered_at: Optional[datetime] = None


class BaseNotificationChannel(ABC):
    """Abstract base class for notification channels."""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Unique identifier for channel (e.g. 'in_app', 'email')."""
        pass

    @abstractmethod
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
        """Deliver the notification through this channel."""
        pass
