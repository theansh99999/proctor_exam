"""
modules/notifications/schemas.py
--------------------------------
Pydantic v2 schemas for notifications, preferences, announcements, and delivery tracking.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# 1. NOTIFICATION SCHEMAS
# =============================================================================

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    organization_id: Optional[int] = None
    category: str
    event_type: str
    title: str
    message: str
    action_url: Optional[str] = None
    is_read: bool
    read_at: Optional[datetime] = None
    is_dismissed: bool
    dismissed_at: Optional[datetime] = None
    notification_metadata: Optional[str] = None
    delivery_status: str
    created_at: datetime


class NotificationListResponse(BaseModel):
    total: int
    unread_count: int
    page: int
    page_size: int
    items: List[NotificationOut]


class UnreadCountResponse(BaseModel):
    unread_count: int


# =============================================================================
# 2. PREFERENCE SCHEMAS
# =============================================================================

class NotificationPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email_enabled: bool = True
    in_app_enabled: bool = True
    reminders_enabled: bool = True
    results_enabled: bool = True
    announcements_enabled: bool = True
    updated_at: Optional[datetime] = None


class NotificationPreferenceUpdate(BaseModel):
    email_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
    reminders_enabled: Optional[bool] = None
    results_enabled: Optional[bool] = None
    announcements_enabled: Optional[bool] = None


# =============================================================================
# 3. ANNOUNCEMENT SCHEMAS
# =============================================================================

class AnnouncementCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    content: str = Field(..., min_length=2)
    target_type: str = Field(..., description="assessment, group, candidate, all_assigned")
    target_id: Optional[int] = Field(None, description="exam_id, group_id, or student_user_id")
    channel: str = Field("both", description="in_app, email, both")


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: Optional[int] = None
    sender_id: int
    title: str
    content: str
    target_type: str
    target_id: Optional[int] = None
    channel: str
    recipient_count: int
    status: str
    created_at: datetime


class AnnouncementDeliveryBreakdown(BaseModel):
    in_app_delivered: int = 0
    in_app_failed: int = 0
    email_delivered: int = 0
    email_failed: int = 0
    total_recipients: int = 0


class AnnouncementStatusResponse(BaseModel):
    announcement: AnnouncementOut
    delivery: AnnouncementDeliveryBreakdown


class AnnouncementListResponse(BaseModel):
    total: int
    items: List[AnnouncementOut]


# =============================================================================
# 4. DELIVERY AUDIT SCHEMAS
# =============================================================================

class NotificationDeliveryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_id: Optional[int] = None
    announcement_id: Optional[int] = None
    organization_id: Optional[int] = None
    recipient_id: int
    channel: str
    event_type: str
    idempotency_key: Optional[str] = None
    status: str
    retry_count: int
    error_message: Optional[str] = None
    created_at: datetime
    delivered_at: Optional[datetime] = None


class DeliveryLogListResponse(BaseModel):
    total: int
    items: List[NotificationDeliveryLogOut]
