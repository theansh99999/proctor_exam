"""
modules/notifications/service.py
--------------------------------
Centralized Notification and Communication Service for ExamProctor.
Handles in-app alerts, email dispatch, preferences, automated lifecycle events,
examiner announcements, scheduled reminders, idempotency, and audit logging.
"""
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timedelta
import json
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_, or_
from fastapi import HTTPException, status

import models
from time_utils import utc_now, to_utc, to_utc_iso
from core.rbac import (
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin,
    is_candidate,
    normalize_role,
    PlatformRole
)
from modules.notifications.channels.in_app import InAppNotificationChannel
from modules.notifications.channels.email import EmailNotificationChannel
from modules.notifications.templates.renderer import render_event_content
from modules.notifications.schemas import (
    NotificationPreferenceUpdate,
    AnnouncementCreateRequest,
    AnnouncementDeliveryBreakdown
)


class NotificationService:

    # =========================================================================
    # 1. USER NOTIFICATION PREFERENCES
    # =========================================================================

    @staticmethod
    def get_or_create_preferences(
        db: Session,
        user_id: int,
        organization_id: Optional[int] = None
    ) -> models.NotificationPreference:
        """Retrieves or initializes default notification preferences for a user."""
        pref = db.query(models.NotificationPreference).filter_by(user_id=user_id).first()
        if not pref:
            pref = models.NotificationPreference(
                user_id=user_id,
                organization_id=organization_id,
                email_enabled=True,
                in_app_enabled=True,
                reminders_enabled=True,
                results_enabled=True,
                announcements_enabled=True,
                created_at=utc_now(),
                updated_at=utc_now()
            )
            db.add(pref)
            db.commit()
            db.refresh(pref)
        return pref

    @staticmethod
    def update_preferences(
        db: Session,
        user_id: int,
        data: NotificationPreferenceUpdate,
        current_user: models.User
    ) -> models.NotificationPreference:
        """Updates preferences. Users can only update their own preferences unless Super Admin."""
        if current_user.id != user_id and not is_super_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update notification preferences for this user."
            )

        pref = NotificationService.get_or_create_preferences(db, user_id, current_user.organization_id)

        if data.email_enabled is not None:
            pref.email_enabled = data.email_enabled
        if data.in_app_enabled is not None:
            pref.in_app_enabled = data.in_app_enabled
        if data.reminders_enabled is not None:
            pref.reminders_enabled = data.reminders_enabled
        if data.results_enabled is not None:
            pref.results_enabled = data.results_enabled
        if data.announcements_enabled is not None:
            pref.announcements_enabled = data.announcements_enabled

        pref.updated_at = utc_now()
        db.commit()
        db.refresh(pref)
        return pref

    # =========================================================================
    # 2. IN-APP NOTIFICATION CENTER (QUERYING & ACTIONS)
    # =========================================================================

    @staticmethod
    def list_notifications(
        db: Session,
        current_user: models.User,
        category: Optional[str] = None,
        is_read: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None
    ) -> Tuple[List[models.Notification], int, int]:
        """
        Lists notifications scoped to authenticated user and organization.
        Returns: (items, total_count, unread_count)
        """
        query = db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_dismissed.is_(False)
        )

        # Multi-tenant organization isolation
        if current_user.organization_id is not None and not is_super_admin(current_user):
            query = query.filter(
                or_(
                    models.Notification.organization_id == current_user.organization_id,
                    models.Notification.organization_id.is_(None)
                )
            )

        if category:
            query = query.filter(models.Notification.category == category)

        if is_read is not None:
            query = query.filter(models.Notification.is_read.is_(is_read))

        if search:
            query = query.filter(
                or_(
                    models.Notification.title.ilike(f"%{search}%"),
                    models.Notification.message.ilike(f"%{search}%")
                )
            )

        total = query.count()

        # Unread count (across all non-dismissed for this user)
        unread_count = db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_dismissed.is_(False),
            models.Notification.is_read.is_(False)
        ).count()

        # Pagination
        offset = (page - 1) * page_size
        items = query.order_by(desc(models.Notification.created_at)).offset(offset).limit(page_size).all()

        return items, total, unread_count

    @staticmethod
    def get_unread_count(db: Session, current_user: models.User) -> int:
        """Fast lookup for unread notifications badge counter."""
        return db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_dismissed.is_(False),
            models.Notification.is_read.is_(False)
        ).count()

    @staticmethod
    def mark_as_read(db: Session, notification_id: int, current_user: models.User) -> models.Notification:
        """Marks a notification as read with ownership validation."""
        notif = db.query(models.Notification).filter_by(id=notification_id).first()
        if not notif:
            raise HTTPException(status_code=404, detail="Notification not found.")

        if notif.user_id != current_user.id and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to access this notification.")

        notif.is_read = True
        notif.read_at = utc_now()
        db.commit()
        db.refresh(notif)
        return notif

    @staticmethod
    def mark_all_as_read(db: Session, current_user: models.User) -> int:
        """Marks all active notifications as read for current user."""
        now = utc_now()
        updated = db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_read.is_(False),
            models.Notification.is_dismissed.is_(False)
        ).update(
            {"is_read": True, "read_at": now},
            synchronize_session=False
        )
        db.commit()
        return updated

    @staticmethod
    def dismiss_notification(db: Session, notification_id: int, current_user: models.User) -> None:
        """Soft-deletes / dismisses a notification from user's view."""
        notif = db.query(models.Notification).filter_by(id=notification_id).first()
        if not notif:
            raise HTTPException(status_code=404, detail="Notification not found.")

        if notif.user_id != current_user.id and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to dismiss this notification.")

        notif.is_dismissed = True
        notif.dismissed_at = utc_now()
        db.commit()

    # =========================================================================
    # 3. CORE NOTIFICATION DISPATCH (IDEMPOTENCY, PREFERENCES & MULTI-CHANNEL)
    # =========================================================================

    @staticmethod
    def send_notification(
        db: Session,
        recipient_id: int,
        category: str,
        event_type: str,
        title: str,
        message: str,
        organization_id: Optional[int] = None,
        channels: Optional[List[str]] = None,
        action_url: Optional[str] = None,
        html_content: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        announcement_id: Optional[int] = None,
        event_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatches notification to a user respecting preferences, channels, and idempotency.
        External failures (e.g. SMTP) never crash or impede callers.
        """
        recipient = db.query(models.User).filter_by(id=recipient_id).first()
        if not recipient:
            return {"status": "failed", "error": "Recipient user not found"}

        if organization_id is None:
            organization_id = recipient.organization_id

        # Check idempotency
        if idempotency_key:
            existing_log = db.query(models.NotificationDeliveryLog).filter_by(
                idempotency_key=idempotency_key,
                status="delivered"
            ).first()
            if existing_log:
                return {
                    "status": "skipped",
                    "reason": "Duplicate notification skipped via idempotency key.",
                    "idempotency_key": idempotency_key
                }

        # Check User Preferences
        prefs = NotificationService.get_or_create_preferences(db, recipient_id, organization_id)

        # Event-specific preference filtering
        if category == "reminder" and not prefs.reminders_enabled:
            return {"status": "skipped", "reason": "User disabled assessment reminders."}
        if category == "evaluation" and not prefs.results_enabled:
            return {"status": "skipped", "reason": "User disabled result notifications."}
        if category == "announcement" and not prefs.announcements_enabled:
            return {"status": "skipped", "reason": "User disabled announcement notifications."}

        # Determine target channels
        req_channels = channels or ["in_app", "email"]
        final_channels = []

        if "in_app" in req_channels and prefs.in_app_enabled:
            final_channels.append("in_app")
        if "email" in req_channels and prefs.email_enabled:
            final_channels.append("email")

        if not final_channels:
            return {"status": "skipped", "reason": "All requested channels disabled by user preferences."}

        meta = dict(event_metadata or {})
        meta["category"] = category
        meta["event_type"] = event_type

        delivery_results = {}
        created_notif_id = None

        # 1. Deliver In-App
        if "in_app" in final_channels:
            in_app_ch = InAppNotificationChannel(db, organization_id)
            res_inapp = in_app_ch.deliver(
                recipient_id=recipient_id,
                recipient_email=recipient.email,
                recipient_name=recipient.name,
                title=title,
                message=message,
                html_content=html_content,
                action_url=action_url,
                event_metadata=meta
            )
            created_notif_id = meta.get("_created_notification_id")
            delivery_results["in_app"] = res_inapp.success

            log_inapp = models.NotificationDeliveryLog(
                notification_id=created_notif_id,
                announcement_id=announcement_id,
                organization_id=organization_id,
                recipient_id=recipient_id,
                channel="in_app",
                event_type=event_type,
                idempotency_key=f"{idempotency_key}:in_app" if idempotency_key else None,
                status="delivered" if res_inapp.success else "failed",
                error_message=res_inapp.error_message,
                created_at=utc_now(),
                delivered_at=res_inapp.delivered_at
            )
            db.add(log_inapp)

        # 2. Deliver Email
        if "email" in final_channels:
            email_ch = EmailNotificationChannel()
            res_email = email_ch.deliver(
                recipient_id=recipient_id,
                recipient_email=recipient.email,
                recipient_name=recipient.name,
                title=title,
                message=message,
                html_content=html_content,
                action_url=action_url,
                event_metadata=meta
            )
            delivery_results["email"] = res_email.success

            log_email = models.NotificationDeliveryLog(
                notification_id=created_notif_id,
                announcement_id=announcement_id,
                organization_id=organization_id,
                recipient_id=recipient_id,
                channel="email",
                event_type=event_type,
                idempotency_key=f"{idempotency_key}:email" if idempotency_key else None,
                status="delivered" if res_email.success else "failed",
                retry_count=1 if not res_email.success and res_email.retryable else 0,
                error_message=res_email.error_message,
                created_at=utc_now(),
                delivered_at=res_email.delivered_at
            )
            db.add(log_email)

        # Primary idempotency record to prevent future full duplicate runs
        if idempotency_key:
            overall_success = any(delivery_results.values())
            main_log = models.NotificationDeliveryLog(
                notification_id=created_notif_id,
                announcement_id=announcement_id,
                organization_id=organization_id,
                recipient_id=recipient_id,
                channel="composite",
                event_type=event_type,
                idempotency_key=idempotency_key,
                status="delivered" if overall_success else "failed",
                created_at=utc_now(),
                delivered_at=utc_now() if overall_success else None
            )
            db.add(main_log)

        db.commit()

        return {
            "status": "delivered",
            "notification_id": created_notif_id,
            "channels": delivery_results
        }

    # =========================================================================
    # 4. AUTOMATED ASSESSMENT NOTIFICATIONS
    # =========================================================================

    @staticmethod
    def get_assigned_candidate_ids(db: Session, exam_id: int) -> Set[int]:
        """Finds all candidate user IDs assigned to an assessment."""
        candidate_ids: Set[int] = set()

        # 1. From AssessmentAssignment table (direct candidate & groups)
        direct_assigns = db.query(models.AssessmentAssignment).filter(
            models.AssessmentAssignment.assessment_id == exam_id,
            models.AssessmentAssignment.candidate_id.isnot(None)
        ).all()
        for a in direct_assigns:
            if a.candidate_id:
                candidate_ids.add(a.candidate_id)

        group_assigns = db.query(models.AssessmentAssignment).filter(
            models.AssessmentAssignment.assessment_id == exam_id,
            models.AssessmentAssignment.group_id.isnot(None)
        ).all()
        grp_ids = [a.group_id for a in group_assigns if a.group_id]

        # 2. Legacy Group on Exam
        exam = db.query(models.Exam).filter_by(id=exam_id).first()
        if exam and exam.group_id:
            grp_ids.append(exam.group_id)

        if grp_ids:
            members = db.query(models.GroupMember).filter(
                models.GroupMember.group_id.in_(grp_ids)
            ).all()
            for m in members:
                if m.student_id:
                    candidate_ids.add(m.student_id)
                elif m.student_email:
                    # Look up user by email
                    u = db.query(models.User).filter_by(email=m.student_email).first()
                    if u:
                        candidate_ids.add(u.id)

        return candidate_ids

    @staticmethod
    def trigger_assessment_lifecycle_event(
        db: Session,
        event_type: str,
        exam_id: int,
        extra_params: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Dispatches assessment lifecycle notifications to all assigned candidates:
        - assessment_published
        - assessment_scheduled
        - assignment_created
        - assessment_rescheduled
        - assessment_cancelled
        - assessment_approaching_start
        """
        exam = db.query(models.Exam).filter_by(id=exam_id).first()
        if not exam:
            return 0

        candidate_ids = NotificationService.get_assigned_candidate_ids(db, exam_id)
        if not candidate_ids:
            return 0

        params = dict(extra_params or {})
        params["exam_title"] = exam.title
        params["action_url"] = f"/student/take_exam/{exam.id}"
        if exam.start_time:
            params["start_time"] = to_utc_iso(exam.start_time)
        if exam.end_time:
            params["end_time"] = to_utc_iso(exam.end_time)

        delivered_count = 0
        for cid in candidate_ids:
            cand = db.query(models.User).filter_by(id=cid).first()
            if not cand:
                continue

            title, msg, html = render_event_content(event_type, cand.name, params)
            idem_key = f"{event_type}:{exam.id}:{cid}"

            res = NotificationService.send_notification(
                db=db,
                recipient_id=cid,
                category="lifecycle",
                event_type=event_type,
                title=title,
                message=msg,
                organization_id=exam.organization_id,
                action_url=params.get("action_url"),
                html_content=html,
                idempotency_key=idem_key,
                event_metadata={"exam_id": exam.id}
            )
            if res.get("status") == "delivered":
                delivered_count += 1

        return delivered_count

    @staticmethod
    def trigger_candidate_activity_event(
        db: Session,
        event_type: str,
        exam_id: int,
        student_id: int,
        extra_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatches candidate activity alerts:
        - assessment_submitted
        - assessment_auto_submitted
        - assessment_expired
        """
        exam = db.query(models.Exam).filter_by(id=exam_id).first()
        student = db.query(models.User).filter_by(id=student_id).first()
        if not exam or not student:
            return {"status": "failed", "error": "Exam or student not found"}

        params = dict(extra_params or {})
        params["exam_title"] = exam.title
        params["action_url"] = "/student/dashboard"

        title, msg, html = render_event_content(event_type, student.name, params)
        idem_key = f"{event_type}:{exam.id}:{student.id}:{uuid.uuid4().hex[:6]}"

        return NotificationService.send_notification(
            db=db,
            recipient_id=student.id,
            category="candidate",
            event_type=event_type,
            title=title,
            message=msg,
            organization_id=exam.organization_id,
            action_url=params.get("action_url"),
            html_content=html,
            idempotency_key=idem_key,
            event_metadata={"exam_id": exam.id}
        )

    @staticmethod
    def trigger_evaluation_event(
        db: Session,
        event_type: str,
        exam_id: int,
        student_id: int,
        extra_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatches evaluation and result notifications:
        - manual_grading_completed
        - result_released
        - result_revised
        - feedback_available
        Enforces policy: NEVER send result notifications for unreleased results!
        """
        exam = db.query(models.Exam).filter_by(id=exam_id).first()
        student = db.query(models.User).filter_by(id=student_id).first()
        if not exam or not student:
            return {"status": "failed", "error": "Exam or student not found"}

        # Enforce unreleased result check
        if event_type in ("result_released", "result_revised", "feedback_available"):
            # Check exam release or specific result release flag
            exam_released = getattr(exam, "results_released", False)
            res_rec = db.query(models.ExamResult).filter_by(
                exam_id=exam_id,
                student_id=student_id
            ).first()
            result_released = getattr(res_rec, "is_released", False) if res_rec else False

            if not exam_released and not result_released:
                return {
                    "status": "skipped",
                    "reason": "Assessment results are unreleased. Notification suppressed."
                }

        params = dict(extra_params or {})
        params["exam_title"] = exam.title
        params["action_url"] = f"/student/my_report/{exam.id}"

        title, msg, html = render_event_content(event_type, student.name, params)
        idem_key = f"{event_type}:{exam.id}:{student.id}"

        return NotificationService.send_notification(
            db=db,
            recipient_id=student.id,
            category="evaluation",
            event_type=event_type,
            title=title,
            message=msg,
            organization_id=exam.organization_id,
            action_url=params.get("action_url"),
            html_content=html,
            idempotency_key=idem_key,
            event_metadata={"exam_id": exam.id}
        )

    # =========================================================================
    # 5. EXAMINER COMMUNICATION (ANNOUNCEMENTS)
    # =========================================================================

    @staticmethod
    def send_announcement(
        db: Session,
        req: AnnouncementCreateRequest,
        current_user: models.User
    ) -> models.Announcement:
        """
        Allows examiners/admins to broadcast announcements to assigned candidates,
        groups, or assessment cohorts with rigorous multi-tenant RBAC validation.
        """
        if not is_examiner_or_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only examiners and administrators can broadcast announcements."
            )

        candidate_ids: Set[int] = set()
        org_id = current_user.organization_id

        # Validate target and collect candidate recipients
        if req.target_type == "assessment":
            if not req.target_id:
                raise HTTPException(status_code=400, detail="target_id (exam_id) required for assessment target.")
            exam = db.query(models.Exam).filter_by(id=req.target_id).first()
            if not exam:
                raise HTTPException(status_code=404, detail="Assessment not found.")

            # Cross-organization check
            if org_id is not None and exam.organization_id != org_id and not is_super_admin(current_user):
                raise HTTPException(status_code=403, detail="Cannot send announcements across organizations.")

            # Examiner authorization check
            if normalize_role(current_user.role) == PlatformRole.EXAMINER:
                if exam.creator_id != current_user.id and exam.group and exam.group.teacher_id != current_user.id:
                    raise HTTPException(status_code=403, detail="Not authorized to announce to this assessment.")

            candidate_ids = NotificationService.get_assigned_candidate_ids(db, exam.id)

        elif req.target_type == "group":
            if not req.target_id:
                raise HTTPException(status_code=400, detail="target_id (group_id) required for group target.")
            group = db.query(models.Group).filter_by(id=req.target_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="Group not found.")

            # Cross-org check
            if org_id is not None and group.organization_id != org_id and not is_super_admin(current_user):
                raise HTTPException(status_code=403, detail="Cannot send announcements across organizations.")

            # Examiner check
            if normalize_role(current_user.role) == PlatformRole.EXAMINER:
                if group.teacher_id != current_user.id:
                    raise HTTPException(status_code=403, detail="Not authorized to announce to this group.")

            members = db.query(models.GroupMember).filter_by(group_id=group.id).all()
            for m in members:
                if m.student_id:
                    candidate_ids.add(m.student_id)
                elif m.student_email:
                    u = db.query(models.User).filter_by(email=m.student_email).first()
                    if u:
                        candidate_ids.add(u.id)

        elif req.target_type == "candidate":
            if not req.target_id:
                raise HTTPException(status_code=400, detail="target_id (user_id) required for candidate target.")
            cand = db.query(models.User).filter_by(id=req.target_id).first()
            if not cand or not is_candidate(cand):
                raise HTTPException(status_code=404, detail="Candidate not found.")

            # Cross-org check
            if org_id is not None and cand.organization_id != org_id and not is_super_admin(current_user):
                raise HTTPException(status_code=403, detail="Cannot send announcements across organizations.")

            candidate_ids.add(cand.id)

        elif req.target_type == "all_assigned":
            # Examiner's entire pool of students across their groups
            groups = db.query(models.Group).filter_by(teacher_id=current_user.id).all()
            for g in groups:
                for m in g.members:
                    if m.student_id:
                        candidate_ids.add(m.student_id)
                    elif m.student_email:
                        u = db.query(models.User).filter_by(email=m.student_email).first()
                        if u:
                            candidate_ids.add(u.id)

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported target_type: '{req.target_type}'.")

        # Create Announcement Record
        announcement = models.Announcement(
            organization_id=org_id,
            sender_id=current_user.id,
            title=req.title,
            content=req.content,
            target_type=req.target_type,
            target_id=req.target_id,
            channel=req.channel,
            recipient_count=len(candidate_ids),
            status="sent",
            created_at=utc_now()
        )
        db.add(announcement)
        db.commit()
        db.refresh(announcement)

        # Dispatch notifications to each candidate
        channel_list = ["in_app", "email"] if req.channel == "both" else [req.channel]
        params = {
            "title": req.title,
            "content": req.content,
            "action_url": "/dashboard"
        }

        for cid in candidate_ids:
            cand = db.query(models.User).filter_by(id=cid).first()
            if not cand:
                continue

            title, msg, html = render_event_content("announcement", cand.name, params)
            idem_key = f"announcement:{announcement.id}:{cid}"

            NotificationService.send_notification(
                db=db,
                recipient_id=cid,
                category="announcement",
                event_type="announcement",
                title=title,
                message=msg,
                organization_id=org_id,
                channels=channel_list,
                action_url="/dashboard",
                html_content=html,
                idempotency_key=idem_key,
                announcement_id=announcement.id,
                event_metadata={"announcement_id": announcement.id}
            )

        try:
            from modules.admin.service import AdminService
            AdminService.log_audit(
                db=db,
                action="announcement.create",
                entity_type="announcement",
                entity_id=str(announcement.id),
                actor_id=current_user.id,
                org_id=org_id,
                metadata={"title": announcement.title, "recipients": len(candidate_ids), "target_type": announcement.target_type}
            )
        except Exception:
            pass

        return announcement

    @staticmethod
    def list_announcements(
        db: Session,
        current_user: models.User,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[models.Announcement], int]:
        """Lists announcement history with RBAC scoping."""
        query = db.query(models.Announcement)
        if not is_super_admin(current_user):
            if is_org_admin(current_user):
                query = query.filter_by(organization_id=current_user.organization_id)
            else:
                query = query.filter_by(sender_id=current_user.id)

        total = query.count()
        items = query.order_by(desc(models.Announcement.created_at)).offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    @staticmethod
    def get_announcement_delivery_status(
        db: Session,
        announcement_id: int,
        current_user: models.User
    ) -> AnnouncementDeliveryBreakdown:
        """Calculates in-app vs email delivery metrics for an announcement."""
        ann = db.query(models.Announcement).filter_by(id=announcement_id).first()
        if not ann:
            raise HTTPException(status_code=404, detail="Announcement not found.")

        if ann.sender_id != current_user.id and not is_org_admin(current_user) and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to view this announcement status.")

        logs = db.query(models.NotificationDeliveryLog).filter_by(announcement_id=announcement_id).all()

        in_app_ok = sum(1 for l in logs if l.channel == "in_app" and l.status == "delivered")
        in_app_err = sum(1 for l in logs if l.channel == "in_app" and l.status == "failed")
        email_ok = sum(1 for l in logs if l.channel == "email" and l.status == "delivered")
        email_err = sum(1 for l in logs if l.channel == "email" and l.status == "failed")

        return AnnouncementDeliveryBreakdown(
            in_app_delivered=in_app_ok,
            in_app_failed=in_app_err,
            email_delivered=email_ok,
            email_failed=email_err,
            total_recipients=ann.recipient_count
        )

    # =========================================================================
    # 6. SCHEDULED REMINDERS ENGINE
    # =========================================================================

    @staticmethod
    def process_scheduled_reminders(db: Session, reference_time: Optional[datetime] = None) -> Dict[str, int]:
        """
        Scans upcoming assessments for 24-hour and 1-hour reminders.
        Suppresses reminders for:
        - Cancelled / draft / archived assessments
        - Candidates who have already submitted
        - Duplicate reminder runs via idempotency keys
        """
        now = to_utc(reference_time) or utc_now()
        reminders_sent_24h = 0
        reminders_sent_1h = 0

        # Look for published/scheduled exams starting in the future
        exams = db.query(models.Exam).filter(
            models.Exam.status.notin_(["draft", "archived", "cancelled"]),
            models.Exam.start_time > now
        ).all()

        for exam in exams:
            st = to_utc(exam.start_time)
            diff_seconds = (st - now).total_seconds()
            hours_to_start = diff_seconds / 3600.0

            # Determine reminder window
            is_24h = (23.0 <= hours_to_start <= 25.0)
            is_1h = (0.8 <= hours_to_start <= 1.2)

            if not (is_24h or is_1h):
                continue

            event_type = "assessment_reminder_24h" if is_24h else "assessment_reminder_1h"
            candidate_ids = NotificationService.get_assigned_candidate_ids(db, exam.id)

            # Find already submitted students
            submitted_student_ids = {
                s.student_id for s in db.query(models.Submission).filter_by(exam_id=exam.id).all()
            }
            # Also check ExamSession submitted
            sess_submitted = {
                s.student_id for s in db.query(models.ExamSession).filter(
                    models.ExamSession.exam_id == exam.id,
                    models.ExamSession.status.in_(["submitted", "auto_submitted"])
                ).all()
            }
            already_done = submitted_student_ids.union(sess_submitted)

            params = {
                "exam_title": exam.title,
                "start_time": to_utc_iso(exam.start_time),
                "action_url": f"/student/take_exam/{exam.id}"
            }

            for cid in candidate_ids:
                if cid in already_done:
                    continue  # Skip submitted candidate

                cand = db.query(models.User).filter_by(id=cid).first()
                if not cand:
                    continue

                title, msg, html = render_event_content(event_type, cand.name, params)
                # Strict idempotency key ensures no duplicate reminders
                idem_key = f"{event_type}:{exam.id}:{cid}"

                res = NotificationService.send_notification(
                    db=db,
                    recipient_id=cid,
                    category="reminder",
                    event_type=event_type,
                    title=title,
                    message=msg,
                    organization_id=exam.organization_id,
                    action_url=params["action_url"],
                    html_content=html,
                    idempotency_key=idem_key,
                    event_metadata={"exam_id": exam.id}
                )

                if res.get("status") == "delivered":
                    if is_24h:
                        reminders_sent_24h += 1
                    else:
                        reminders_sent_1h += 1

        return {
            "reminders_sent_24h": reminders_sent_24h,
            "reminders_sent_1h": reminders_sent_1h,
            "total_sent": reminders_sent_24h + reminders_sent_1h
        }
