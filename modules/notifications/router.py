"""
modules/notifications/router.py
-------------------------------
FastAPI router for Notification Center & Communication APIs under /api/v1/notifications/.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import models
import database
import auth
from core.rbac import (
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin
)
from modules.notifications.service import NotificationService
from modules.notifications.schemas import (
    NotificationOut,
    NotificationListResponse,
    UnreadCountResponse,
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
    AnnouncementCreateRequest,
    AnnouncementOut,
    AnnouncementStatusResponse,
    AnnouncementListResponse,
    NotificationDeliveryLogOut,
    DeliveryLogListResponse
)

router = APIRouter(tags=["Notifications"])


# =============================================================================
# 1. IN-APP NOTIFICATIONS
# =============================================================================

@router.get("/", response_model=NotificationListResponse)
def list_notifications(
    category: Optional[str] = Query(None, description="lifecycle, candidate, evaluation, announcement, reminder, system"),
    is_read: Optional[bool] = Query(None, description="Filter by read/unread state"),
    search: Optional[str] = Query(None, description="Search keyword in title or message"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Lists notifications for the current authenticated user, scoped to organization."""
    items, total, unread = NotificationService.list_notifications(
        db=db,
        current_user=current_user,
        category=category,
        is_read=is_read,
        page=page,
        page_size=page_size,
        search=search
    )
    return NotificationListResponse(
        total=total,
        unread_count=unread,
        page=page,
        page_size=page_size,
        items=[NotificationOut.model_validate(n) for n in items]
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Returns unread notification badge count."""
    count = NotificationService.get_unread_count(db, current_user)
    return UnreadCountResponse(unread_count=count)


@router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Marks all active notifications as read."""
    count = NotificationService.mark_all_as_read(db, current_user)
    return {"status": "success", "marked_read_count": count}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Marks a single notification as read."""
    notif = NotificationService.mark_as_read(db, notification_id, current_user)
    return NotificationOut.model_validate(notif)


@router.delete("/{notification_id}")
def dismiss_notification(
    notification_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Dismisses / soft-deletes a notification."""
    NotificationService.dismiss_notification(db, notification_id, current_user)
    return {"status": "success", "message": "Notification dismissed."}


# =============================================================================
# 2. USER PREFERENCES
# =============================================================================

@router.get("/preferences", response_model=NotificationPreferenceOut)
def get_preferences(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Retrieves notification preferences for authenticated user."""
    pref = NotificationService.get_or_create_preferences(db, current_user.id, current_user.organization_id)
    return NotificationPreferenceOut.model_validate(pref)


@router.put("/preferences", response_model=NotificationPreferenceOut)
@router.post("/preferences", response_model=NotificationPreferenceOut)
def update_preferences(
    data: NotificationPreferenceUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Updates notification preferences for authenticated user."""
    pref = NotificationService.update_preferences(db, current_user.id, data, current_user)
    return NotificationPreferenceOut.model_validate(pref)


# =============================================================================
# 3. EXAMINER COMMUNICATION (ANNOUNCEMENTS)
# =============================================================================

@router.post("/announcements", response_model=AnnouncementOut)
def send_announcement(
    req: AnnouncementCreateRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Broadcasts an announcement to assigned candidates, groups, or assessments."""
    ann = NotificationService.send_announcement(db, req, current_user)
    return AnnouncementOut.model_validate(ann)


@router.get("/announcements", response_model=AnnouncementListResponse)
def list_announcements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Lists announcement history created by current examiner or organization."""
    items, total = NotificationService.list_announcements(db, current_user, page=page, page_size=page_size)
    return AnnouncementListResponse(
        total=total,
        items=[AnnouncementOut.model_validate(a) for a in items]
    )


@router.get("/announcements/{announcement_id}/status", response_model=AnnouncementStatusResponse)
def get_announcement_status(
    announcement_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Views delivery status and channel breakdown for an announcement."""
    ann = db.query(models.Announcement).filter_by(id=announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found.")

    delivery = NotificationService.get_announcement_delivery_status(db, announcement_id, current_user)
    return AnnouncementStatusResponse(
        announcement=AnnouncementOut.model_validate(ann),
        delivery=delivery
    )


# =============================================================================
# 4. DELIVERY AUDIT & SCHEDULED REMINDERS
# =============================================================================

@router.get("/delivery-logs", response_model=DeliveryLogListResponse)
def get_delivery_logs(
    channel: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Views sanitized delivery audit logs with role-based scoping."""
    query = db.query(models.NotificationDeliveryLog)
    if not is_super_admin(current_user):
        if is_org_admin(current_user):
            query = query.filter_by(organization_id=current_user.organization_id)
        else:
            # Examiner: logs for recipients in examiner's scope or announcements sent by examiner
            examiner_ann_ids = [
                a.id for a in db.query(models.Announcement.id).filter_by(sender_id=current_user.id).all()
            ]
            query = query.filter(models.NotificationDeliveryLog.announcement_id.in_(examiner_ann_ids))

    if channel:
        query = query.filter_by(channel=channel)
    if status_filter:
        query = query.filter_by(status=status_filter)

    total = query.count()
    items = query.order_by(models.NotificationDeliveryLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return DeliveryLogListResponse(
        total=total,
        items=[NotificationDeliveryLogOut.model_validate(l) for l in items]
    )


@router.post("/reminders/trigger")
def trigger_reminders(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Triggers scan for scheduled 24h/1h reminders."""
    result = NotificationService.process_scheduled_reminders(db)
    return {"status": "success", "result": result}
