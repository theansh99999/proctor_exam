"""
modules/admin/service.py
------------------------
Service layer for Phase 10 Platform Administration & System Configuration.
Enforces:
- Strict RBAC and Organization Isolation
- Privilege Escalation Prevention
- Append-Only Audit Logging
- Data Integrity (Deactivation/Suspension without data deletion)
- Sensitive Information Masking (never expose password hashes)
"""
import json
import csv
import io
import secrets
import string
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, asc, or_, and_
from fastapi import HTTPException, status

import models
import auth
from time_utils import utc_now, to_utc
from core.rbac import (
    PlatformRole,
    normalize_role,
    is_super_admin,
    is_org_admin,
    enforce_org_access
)
from modules.admin.schemas import (
    OrganizationCreateAdmin,
    OrganizationUpdateAdmin,
    UserCreateAdmin,
    UserUpdateAdmin,
    BulkImportResult
)
from modules.analytics.service import AnalyticsService


class AdminService:

    # =========================================================================
    # 1. AUDIT LOGGING (APPEND-ONLY)
    # =========================================================================

    @staticmethod
    def log_audit(
        db: Session,
        action: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        actor_id: Optional[int] = None,
        org_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> models.AuditLog:
        """
        Record an immutable audit log entry.
        Sanitizes metadata to ensure no passwords, hashes, tokens or secrets are stored.
        """
        sanitized_meta = None
        if metadata:
            sanitized_meta = {}
            for k, v in metadata.items():
                k_lower = k.lower()
                if any(secret_term in k_lower for secret_term in ("password", "hash", "token", "secret", "auth_key", "credentials")):
                    sanitized_meta[k] = "[REDACTED]"
                else:
                    sanitized_meta[k] = v

        entry = models.AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            actor_id=actor_id,
            organization_id=org_id,
            ip_address=ip_address,
            metadata_json=json.dumps(sanitized_meta) if sanitized_meta else None,
            created_at=utc_now()
        )
        db.add(entry)
        try:
            db.commit()
            db.refresh(entry)
        except Exception:
            db.rollback()
            # In case caller is in a transaction, don't break the main flow but re-raise if needed
            raise
        return entry

    @staticmethod
    def get_audit_logs(
        db: Session,
        current_user: models.User,
        org_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Search audit logs with strict role and organization filtering.
        Super Admin: can view all or filter by org.
        Org Admin: strictly scoped to own organization.
        """
        query = db.query(models.AuditLog).options(
            joinedload(models.AuditLog.actor),
            joinedload(models.AuditLog.organization)
        )

        if is_super_admin(current_user):
            if org_id is not None:
                query = query.filter(models.AuditLog.organization_id == org_id)
        elif is_org_admin(current_user):
            # Org admin can ONLY see logs for their organization
            query = query.filter(models.AuditLog.organization_id == current_user.organization_id)
        else:
            raise HTTPException(status_code=403, detail="Not authorized to view audit logs.")

        if actor_id is not None:
            query = query.filter(models.AuditLog.actor_id == actor_id)
        if action:
            query = query.filter(models.AuditLog.action == action)
        if entity_type:
            query = query.filter(models.AuditLog.entity_type == entity_type)

        logs = query.order_by(desc(models.AuditLog.created_at)).offset(offset).limit(limit).all()

        results = []
        for log in logs:
            meta = None
            if log.metadata_json:
                try:
                    meta = json.loads(log.metadata_json)
                except Exception:
                    meta = {"raw": log.metadata_json}

            results.append({
                "id": log.id,
                "actor_id": log.actor_id,
                "actor_name": log.actor.name if log.actor else None,
                "actor_email": log.actor.email if log.actor else None,
                "organization_id": log.organization_id,
                "organization_name": log.organization.name if log.organization else None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "ip_address": log.ip_address,
                "metadata": meta,
                "created_at": log.created_at
            })
        return results

    @staticmethod
    def get_audit_logs_paginated(
        db: Session,
        current_user: models.User,
        org_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """
        Search audit logs with strict role and organization filtering with pagination.
        Returns (logs, total_count, total_pages).
        """
        import math
        query = db.query(models.AuditLog).options(
            joinedload(models.AuditLog.actor),
            joinedload(models.AuditLog.organization)
        )

        if is_super_admin(current_user):
            if org_id is not None:
                query = query.filter(models.AuditLog.organization_id == org_id)
        elif is_org_admin(current_user):
            query = query.filter(models.AuditLog.organization_id == current_user.organization_id)
        else:
            raise HTTPException(status_code=403, detail="Not authorized to view audit logs.")

        if actor_id is not None:
            query = query.filter(models.AuditLog.actor_id == actor_id)
        if action:
            query = query.filter(models.AuditLog.action == action)
        if entity_type:
            query = query.filter(models.AuditLog.entity_type == entity_type)

        total_count = query.count()
        total_pages = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        logs = query.order_by(desc(models.AuditLog.created_at)).offset(offset).limit(page_size).all()

        results = []
        for log in logs:
            meta = None
            if log.metadata_json:
                try:
                    meta = json.loads(log.metadata_json)
                except Exception:
                    meta = {"raw": log.metadata_json}

            results.append({
                "id": log.id,
                "actor_id": log.actor_id,
                "actor_name": log.actor.name if log.actor else None,
                "actor_email": log.actor.email if log.actor else None,
                "organization_id": log.organization_id,
                "organization_name": log.organization.name if log.organization else None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "ip_address": log.ip_address,
                "metadata": meta,
                "created_at": log.created_at
            })
        return results, total_count, total_pages

    # =========================================================================
    # 2. SUPER ADMIN DASHBOARD & ACTIVITY
    # =========================================================================

    @staticmethod
    def get_super_admin_dashboard(db: Session, current_user: models.User) -> Dict[str, Any]:
        """
        Aggregates cross-organization platform metrics for Super Admin.
        """
        if not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can access platform dashboard.")

        # Organizations
        total_orgs = db.query(models.Organization).count()
        active_orgs = db.query(models.Organization).filter(
            models.Organization.is_active == True,
            models.Organization.is_suspended == False
        ).count()
        inactive_orgs = db.query(models.Organization).filter(models.Organization.is_active == False).count()
        suspended_orgs = db.query(models.Organization).filter(models.Organization.is_suspended == True).count()

        # Users
        total_users = db.query(models.User).count()
        org_admins_count = db.query(models.User).filter(models.User.role == "org_admin").count()
        examiners_count = db.query(models.User).filter(models.User.role.in_(["examiner", "teacher"])).count()
        candidates_count = db.query(models.User).filter(models.User.role.in_(["candidate", "student"])).count()
        suspended_users_count = db.query(models.User).filter(models.User.is_suspended == True).count()

        # Assessments & Attempts
        total_assessments = db.query(models.Exam).count()
        active_assessments = db.query(models.Exam).filter(models.Exam.status == "active").count()
        completed_assessments = db.query(models.Exam).filter(models.Exam.status == "completed").count()

        # Total attempts from ExamSession or Submission
        total_attempts = db.query(models.ExamSession).count()
        if total_attempts == 0:
            total_attempts = db.query(models.Submission).count()

        # Recent Organizations
        recent_org_records = db.query(models.Organization).order_by(desc(models.Organization.created_at)).limit(5).all()
        recent_orgs = [
            {
                "id": o.id,
                "name": o.name,
                "slug": o.slug,
                "is_active": o.is_active,
                "is_suspended": o.is_suspended,
                "created_at": o.created_at.isoformat() if o.created_at else None
            }
            for o in recent_org_records
        ]

        # Recent Administrative Actions
        recent_logs = db.query(models.AuditLog).options(joinedload(models.AuditLog.actor)).order_by(desc(models.AuditLog.created_at)).limit(8).all()
        recent_actions = [
            {
                "id": l.id,
                "action": l.action,
                "entity_type": l.entity_type,
                "entity_id": l.entity_id,
                "actor_name": l.actor.name if l.actor else "System",
                "created_at": l.created_at.isoformat() if l.created_at else None
            }
            for l in recent_logs
        ]

        # Integration Health
        total_integrations = db.query(models.IntegrationConfig).count()
        active_integrations = db.query(models.IntegrationConfig).filter(models.IntegrationConfig.is_enabled == True).count()
        error_logs_count = db.query(models.IntegrationLog).filter(models.IntegrationLog.status == "error").count()
        integration_health = {
            "total_configured": total_integrations,
            "active_count": active_integrations,
            "error_count": error_logs_count,
            "status": "healthy" if error_logs_count == 0 else "attention_needed"
        }

        # Notification Delivery Health
        total_notifs = db.query(models.NotificationDeliveryLog).count()
        failed_notifs = db.query(models.NotificationDeliveryLog).filter(models.NotificationDeliveryLog.status == "failed").count()
        delivered_notifs = db.query(models.NotificationDeliveryLog).filter(models.NotificationDeliveryLog.status == "delivered").count()
        notification_health = {
            "total_sent": total_notifs,
            "delivered_count": delivered_notifs,
            "failed_count": failed_notifs,
            "delivery_rate_pct": round((delivered_notifs / total_notifs * 100.0), 2) if total_notifs > 0 else 100.0,
            "status": "healthy" if failed_notifs == 0 else "degraded"
        }

        return {
            "total_organizations": total_orgs,
            "active_organizations": active_orgs,
            "inactive_organizations": inactive_orgs,
            "suspended_organizations": suspended_orgs,
            "total_users": total_users,
            "total_org_admins": org_admins_count,
            "total_examiners": examiners_count,
            "total_candidates": candidates_count,
            "suspended_users": suspended_users_count,
            "total_assessments": total_assessments,
            "active_assessments": active_assessments,
            "completed_assessments": completed_assessments,
            "total_attempts": total_attempts,
            "recent_organizations": recent_orgs,
            "recent_audit_actions": recent_actions,
            "integration_health": integration_health,
            "notification_health": notification_health
        }

    @staticmethod
    def get_activity_monitoring(
        db: Session,
        current_user: models.User,
        org_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive administrative activity monitoring:
        Recent activity, failed logins, suspended users, integration failures, email failures.
        """
        # Role boundary
        effective_org_id = None
        if is_super_admin(current_user):
            effective_org_id = org_id
        elif is_org_admin(current_user):
            effective_org_id = current_user.organization_id
        else:
            raise HTTPException(status_code=403, detail="Not authorized to access activity monitoring.")

        # 1. Recent activity
        activity_query = db.query(models.AuditLog).options(joinedload(models.AuditLog.actor))
        if effective_org_id:
            activity_query = activity_query.filter(models.AuditLog.organization_id == effective_org_id)
        recent_activity_records = activity_query.order_by(desc(models.AuditLog.created_at)).limit(20).all()

        recent_activity = [
            {
                "id": a.id,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "actor_id": a.actor_id,
                "actor_name": a.actor.name if a.actor else "System",
                "ip_address": a.ip_address,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in recent_activity_records
        ]

        # 2. Failed logins summary
        failed_logins_query = db.query(models.AuditLog).filter(models.AuditLog.action == "auth.login_failed")
        if effective_org_id:
            failed_logins_query = failed_logins_query.filter(models.AuditLog.organization_id == effective_org_id)
        failed_logins_count = failed_logins_query.count()
        recent_failed_logins = failed_logins_query.order_by(desc(models.AuditLog.created_at)).limit(5).all()

        failed_logins_summary = {
            "total_count": failed_logins_count,
            "recent": [
                {
                    "ip_address": f.ip_address,
                    "metadata": json.loads(f.metadata_json) if f.metadata_json else {},
                    "time": f.created_at.isoformat() if f.created_at else None
                }
                for f in recent_failed_logins
            ]
        }

        # 3. Suspended users summary
        suspended_query = db.query(models.User).filter(models.User.is_suspended == True)
        if effective_org_id:
            suspended_query = suspended_query.filter(models.User.organization_id == effective_org_id)
        suspended_count = suspended_query.count()
        suspended_sample = suspended_query.limit(10).all()

        suspended_users_summary = {
            "total_count": suspended_count,
            "users": [
                {
                    "id": u.id,
                    "name": u.name,
                    "email": u.email,
                    "role": u.role,
                    "organization_id": u.organization_id
                }
                for u in suspended_sample
            ]
        }

        # 4. Integration failures summary
        int_query = db.query(models.IntegrationLog).filter(models.IntegrationLog.status == "error")
        if effective_org_id:
            int_query = int_query.join(models.IntegrationConfig).filter(models.IntegrationConfig.organization_id == effective_org_id)
        int_fail_count = int_query.count()
        int_recent_fails = int_query.order_by(desc(models.IntegrationLog.created_at)).limit(5).all()

        integration_failures_summary = {
            "total_count": int_fail_count,
            "recent": [
                {
                    "id": i.id,
                    "event_type": i.event_type,
                    "error_message": i.error_message,
                    "created_at": i.created_at.isoformat() if i.created_at else None
                }
                for i in int_recent_fails
            ]
        }

        # 5. Email / Notification failures summary
        notif_fail_query = db.query(models.NotificationDeliveryLog).filter(models.NotificationDeliveryLog.status == "failed")
        if effective_org_id:
            notif_fail_query = notif_fail_query.filter(models.NotificationDeliveryLog.organization_id == effective_org_id)
        notif_fail_count = notif_fail_query.count()
        notif_recent_fails = notif_fail_query.order_by(desc(models.NotificationDeliveryLog.created_at)).limit(5).all()

        notification_failures_summary = {
            "total_count": notif_fail_count,
            "recent": [
                {
                    "id": n.id,
                    "channel": n.channel,
                    "event_type": n.event_type,
                    "error_message": n.error_message,
                    "created_at": n.created_at.isoformat() if n.created_at else None
                }
                for n in notif_recent_fails
            ]
        }

        return {
            "recent_activity": recent_activity,
            "failed_logins_summary": failed_logins_summary,
            "suspended_users_summary": suspended_users_summary,
            "integration_failures_summary": integration_failures_summary,
            "notification_failures_summary": notification_failures_summary
        }

    # =========================================================================
    # 3. ORGANIZATION MANAGEMENT
    # =========================================================================

    @staticmethod
    def list_organizations(
        db: Session,
        current_user: models.User,
        status_filter: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List organizations with stats. Super Admin sees all; Org Admin sees own."""
        query = db.query(models.Organization)

        if not is_super_admin(current_user):
            if current_user.organization_id is None:
                return []
            query = query.filter(models.Organization.id == current_user.organization_id)

        if status_filter == "active":
            query = query.filter(models.Organization.is_active == True, models.Organization.is_suspended == False)
        elif status_filter == "inactive":
            query = query.filter(models.Organization.is_active == False)
        elif status_filter == "suspended":
            query = query.filter(models.Organization.is_suspended == True)

        if search:
            search_str = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(models.Organization.name).like(search_str),
                    func.lower(models.Organization.slug).like(search_str)
                )
            )

        orgs = query.order_by(asc(models.Organization.name)).all()

        results = []
        for org in orgs:
            user_count = db.query(models.User).filter(models.User.organization_id == org.id).count()
            exam_count = db.query(models.Exam).filter(models.Exam.organization_id == org.id).count()
            results.append({
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "description": org.description,
                "is_active": bool(org.is_active),
                "is_suspended": bool(org.is_suspended),
                "created_at": org.created_at,
                "updated_at": org.updated_at,
                "total_users": user_count,
                "total_exams": exam_count
            })
        return results

    @staticmethod
    def list_organizations_paginated(
        db: Session,
        current_user: models.User,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """List organizations with pagination, search, and status filter."""
        import math
        query = db.query(models.Organization)

        if not is_super_admin(current_user):
            if current_user.organization_id is None:
                return [], 0, 1
            query = query.filter(models.Organization.id == current_user.organization_id)

        if status_filter == "active":
            query = query.filter(models.Organization.is_active == True, models.Organization.is_suspended == False)
        elif status_filter == "inactive":
            query = query.filter(models.Organization.is_active == False)
        elif status_filter == "suspended":
            query = query.filter(models.Organization.is_suspended == True)

        if search:
            search_str = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(models.Organization.name).like(search_str),
                    func.lower(models.Organization.slug).like(search_str)
                )
            )

        total_count = query.count()
        total_pages = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        orgs = query.order_by(asc(models.Organization.name)).offset(offset).limit(page_size).all()
        results = []
        for org in orgs:
            user_count = db.query(models.User).filter(models.User.organization_id == org.id).count()
            exam_count = db.query(models.Exam).filter(models.Exam.organization_id == org.id).count()
            results.append({
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "description": org.description,
                "is_active": bool(org.is_active),
                "is_suspended": bool(org.is_suspended),
                "created_at": org.created_at,
                "updated_at": org.updated_at,
                "total_users": user_count,
                "total_exams": exam_count
            })
        return results, total_count, total_pages

    @staticmethod
    def create_organization(
        db: Session,
        data: OrganizationCreateAdmin,
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> models.Organization:
        """Create new organization (Super Admin only)."""
        if not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can create organizations.")

        # Check unique name and slug
        if db.query(models.Organization).filter(models.Organization.name == data.name.strip()).first():
            raise HTTPException(status_code=400, detail="Organization name already exists.")
        if db.query(models.Organization).filter(models.Organization.slug == data.slug.strip().lower()).first():
            raise HTTPException(status_code=400, detail="Organization slug already exists.")

        org = models.Organization(
            name=data.name.strip(),
            slug=data.slug.strip().lower(),
            description=data.description,
            is_active=data.is_active,
            is_suspended=data.is_suspended,
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(org)
        db.commit()
        db.refresh(org)

        # If admin_user_id was supplied, associate user to org
        if data.admin_user_id:
            user = db.query(models.User).filter(models.User.id == data.admin_user_id).first()
            if user:
                user.organization_id = org.id
                user.role = "org_admin"
                db.commit()

        # Audit log
        AdminService.log_audit(
            db=db,
            action="org.create",
            entity_type="organization",
            entity_id=str(org.id),
            actor_id=current_user.id,
            org_id=org.id,
            ip_address=ip_address,
            metadata={"name": org.name, "slug": org.slug}
        )
        return org

    @staticmethod
    def get_organization(db: Session, org_id: int, current_user: models.User) -> models.Organization:
        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")
        enforce_org_access(current_user, org_id, resource_name="organization")
        return org

    @staticmethod
    def update_organization(
        db: Session,
        org_id: int,
        data: OrganizationUpdateAdmin,
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> models.Organization:
        org = AdminService.get_organization(db, org_id, current_user)

        # Privilege checks: Org Admin can update details, but CANNOT change is_active or is_suspended
        if not is_super_admin(current_user):
            if data.is_active is not None or data.is_suspended is not None:
                raise HTTPException(status_code=403, detail="Only Super Admins can alter organization active/suspended status.")

        changes = {}
        if data.name is not None and data.name.strip() != org.name:
            existing = db.query(models.Organization).filter(
                models.Organization.name == data.name.strip(),
                models.Organization.id != org_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Organization name already taken.")
            changes["old_name"] = org.name
            org.name = data.name.strip()
            changes["new_name"] = org.name

        if data.slug is not None and data.slug.strip().lower() != org.slug:
            existing_slug = db.query(models.Organization).filter(
                models.Organization.slug == data.slug.strip().lower(),
                models.Organization.id != org_id
            ).first()
            if existing_slug:
                raise HTTPException(status_code=400, detail="Organization slug already taken.")
            changes["old_slug"] = org.slug
            org.slug = data.slug.strip().lower()
            changes["new_slug"] = org.slug

        if data.description is not None:
            org.description = data.description
            changes["description_updated"] = True

        if data.is_active is not None and data.is_active != org.is_active:
            changes["old_is_active"] = org.is_active
            org.is_active = data.is_active
            changes["new_is_active"] = org.is_active

        if data.is_suspended is not None and data.is_suspended != org.is_suspended:
            changes["old_is_suspended"] = org.is_suspended
            org.is_suspended = data.is_suspended
            changes["new_is_suspended"] = org.is_suspended

        org.updated_at = utc_now()
        db.commit()
        db.refresh(org)

        AdminService.log_audit(
            db=db,
            action="org.update",
            entity_type="organization",
            entity_id=str(org.id),
            actor_id=current_user.id,
            org_id=org.id,
            ip_address=ip_address,
            metadata=changes
        )
        return org

    @staticmethod
    def update_organization_status(
        db: Session,
        org_id: int,
        action: str,
        current_user: models.User,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> models.Organization:
        """
        Lifecycle state management: activate, deactivate, suspend, reactivate.
        Super Admin only. Never deletes organization data.
        """
        if not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can alter organization lifecycle status.")

        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        act = action.strip().lower()
        old_state = {"is_active": org.is_active, "is_suspended": org.is_suspended}

        if act == "activate":
            org.is_active = True
            org.is_suspended = False
        elif act == "deactivate":
            org.is_active = False
        elif act == "suspend":
            org.is_suspended = True
        elif act == "reactivate" or act == "unsuspend":
            org.is_suspended = False
            org.is_active = True
        else:
            raise HTTPException(status_code=400, detail=f"Invalid organization status action: '{action}'.")

        org.updated_at = utc_now()
        db.commit()
        db.refresh(org)

        AdminService.log_audit(
            db=db,
            action="org.status_change",
            entity_type="organization",
            entity_id=str(org.id),
            actor_id=current_user.id,
            org_id=org.id,
            ip_address=ip_address,
            metadata={
                "action": act,
                "reason": reason,
                "old_state": old_state,
                "new_state": {"is_active": org.is_active, "is_suspended": org.is_suspended}
            }
        )
        return org

    @staticmethod
    def assign_org_admin(
        db: Session,
        org_id: int,
        user_id: int,
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> models.User:
        """Assign user as Org Admin for the organization."""
        org = AdminService.get_organization(db, org_id, current_user)
        if not is_super_admin(current_user):
            if not (is_org_admin(current_user) and current_user.organization_id == org_id):
                raise HTTPException(status_code=403, detail="Not authorized to assign admin for this organization.")

        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        user.organization_id = org.id
        user.role = "org_admin"
        db.commit()
        db.refresh(user)

        AdminService.log_audit(
            db=db,
            action="org.assign_admin",
            entity_type="organization",
            entity_id=str(org.id),
            actor_id=current_user.id,
            org_id=org.id,
            ip_address=ip_address,
            metadata={"assigned_user_id": user.id, "assigned_email": user.email}
        )
        return user

    @staticmethod
    def get_org_users(
        db: Session,
        org_id: int,
        current_user: models.User,
        role: Optional[str] = None,
        status_filter: Optional[str] = None
    ) -> List[models.User]:
        AdminService.get_organization(db, org_id, current_user)
        query = db.query(models.User).filter(models.User.organization_id == org_id)

        if role:
            norm_r = normalize_role(role)
            if norm_r == PlatformRole.EXAMINER:
                query = query.filter(models.User.role.in_(["examiner", "teacher"]))
            elif norm_r == PlatformRole.CANDIDATE:
                query = query.filter(models.User.role.in_(["candidate", "student"]))
            else:
                query = query.filter(models.User.role == role)

        if status_filter == "active":
            query = query.filter(models.User.is_active == True, models.User.is_suspended == False)
        elif status_filter == "inactive":
            query = query.filter(models.User.is_active == False)
        elif status_filter == "suspended":
            query = query.filter(models.User.is_suspended == True)

        return query.order_by(models.User.name).all()

    @staticmethod
    def get_org_assessments(db: Session, org_id: int, current_user: models.User) -> List[models.Exam]:
        AdminService.get_organization(db, org_id, current_user)
        return db.query(models.Exam).filter(models.Exam.organization_id == org_id).order_by(desc(models.Exam.id)).all()

    @staticmethod
    def get_org_activity(db: Session, org_id: int, current_user: models.User) -> List[Dict[str, Any]]:
        AdminService.get_organization(db, org_id, current_user)
        return AdminService.get_audit_logs(db, current_user, org_id=org_id)

    @staticmethod
    def get_org_analytics(db: Session, org_id: int, current_user: models.User) -> Dict[str, Any]:
        AdminService.get_organization(db, org_id, current_user)
        return AnalyticsService.get_organization_dashboard_metrics(db, current_user, target_org_id=org_id)

    # =========================================================================
    # 4. USER ADMINISTRATION
    # =========================================================================

    @staticmethod
    def list_users(
        db: Session,
        current_user: models.User,
        org_id: Optional[int] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        query = db.query(models.User).options(joinedload(models.User.organization))

        if is_super_admin(current_user):
            if org_id is not None:
                query = query.filter(models.User.organization_id == org_id)
        elif is_org_admin(current_user):
            # Strict tenant isolation
            query = query.filter(models.User.organization_id == current_user.organization_id)
        else:
            raise HTTPException(status_code=403, detail="Not authorized to list users.")

        if role:
            norm_r = normalize_role(role)
            if norm_r == PlatformRole.EXAMINER:
                query = query.filter(models.User.role.in_(["examiner", "teacher"]))
            elif norm_r == PlatformRole.CANDIDATE:
                query = query.filter(models.User.role.in_(["candidate", "student"]))
            else:
                query = query.filter(models.User.role == role)

        if status_filter == "active":
            query = query.filter(models.User.is_active == True, models.User.is_suspended == False)
        elif status_filter == "inactive":
            query = query.filter(models.User.is_active == False)
        elif status_filter == "suspended":
            query = query.filter(models.User.is_suspended == True)

        if search:
            search_str = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(models.User.name).like(search_str),
                    func.lower(models.User.email).like(search_str)
                )
            )

        users = query.order_by(asc(models.User.name)).offset(offset).limit(limit).all()

        results = []
        for u in users:
            results.append({
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "organization_id": u.organization_id,
                "organization_name": u.organization.name if u.organization else None,
                "is_active": getattr(u, "is_active", True),
                "is_suspended": getattr(u, "is_suspended", False)
            })
        return results

    @staticmethod
    def list_users_paginated(
        db: Session,
        current_user: models.User,
        org_id: Optional[int] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """
        List users with filtering and pagination.
        Returns (users, total_count, total_pages).
        """
        import math
        query = db.query(models.User).options(joinedload(models.User.organization))

        if is_super_admin(current_user):
            if org_id is not None:
                query = query.filter(models.User.organization_id == org_id)
        elif is_org_admin(current_user):
            query = query.filter(models.User.organization_id == current_user.organization_id)
        else:
            raise HTTPException(status_code=403, detail="Not authorized to list users.")

        if role:
            norm_r = normalize_role(role)
            if norm_r == PlatformRole.EXAMINER:
                query = query.filter(models.User.role.in_(["examiner", "teacher"]))
            elif norm_r == PlatformRole.CANDIDATE:
                query = query.filter(models.User.role.in_(["candidate", "student"]))
            else:
                query = query.filter(models.User.role == role)

        if status_filter == "active":
            query = query.filter(models.User.is_active == True, models.User.is_suspended == False)
        elif status_filter == "inactive":
            query = query.filter(models.User.is_active == False)
        elif status_filter == "suspended":
            query = query.filter(models.User.is_suspended == True)

        if search:
            search_str = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(models.User.name).like(search_str),
                    func.lower(models.User.email).like(search_str)
                )
            )

        total_count = query.count()
        total_pages = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        users = query.order_by(asc(models.User.name)).offset(offset).limit(page_size).all()

        results = []
        for u in users:
            results.append({
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "organization_id": u.organization_id,
                "organization_name": u.organization.name if u.organization else None,
                "is_active": getattr(u, "is_active", True),
                "is_suspended": getattr(u, "is_suspended", False)
            })
        return results, total_count, total_pages

    @staticmethod
    def get_user_details(db: Session, user_id: int, current_user: models.User) -> models.User:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        if is_super_admin(current_user):
            return user
        if is_org_admin(current_user):
            if user.organization_id != current_user.organization_id:
                raise HTTPException(status_code=403, detail="Access denied: user belongs to different organization.")
            return user
        if current_user.id == user_id:
            return user
        raise HTTPException(status_code=403, detail="Not authorized to view user details.")

    @staticmethod
    def create_user(
        db: Session,
        data: UserCreateAdmin,
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> models.User:
        """
        Create user with strict privilege escalation prevention.
        Org Admin CANNOT create Super Admin or Org Admin accounts.
        Org Admin CANNOT create users outside their own organization.
        """
        target_role = normalize_role(data.role)

        if is_super_admin(current_user):
            target_org_id = data.organization_id
        elif is_org_admin(current_user):
            # Org admin can only create examiners or candidates in own org
            if target_role in (PlatformRole.SUPER_ADMIN, PlatformRole.ORG_ADMIN):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Privilege escalation prevented: Organization Admins cannot create Super Admin or Org Admin accounts."
                )
            target_org_id = current_user.organization_id
        else:
            raise HTTPException(status_code=403, detail="Not authorized to create users.")

        # Duplicate email check
        if db.query(models.User).filter(models.User.email == data.email.strip().lower()).first():
            raise HTTPException(status_code=400, detail="Email already registered.")

        # Org verification
        if target_org_id:
            org = db.query(models.Organization).filter(models.Organization.id == target_org_id).first()
            if not org:
                raise HTTPException(status_code=400, detail="Target organization does not exist.")

        new_user = models.User(
            email=data.email.strip().lower(),
            password_hash=auth.get_password_hash(data.password),
            name=data.name.strip(),
            role=data.role,
            organization_id=target_org_id,
            is_active=data.is_active,
            is_suspended=data.is_suspended
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        AdminService.log_audit(
            db=db,
            action="user.create",
            entity_type="user",
            entity_id=str(new_user.id),
            actor_id=current_user.id,
            org_id=target_org_id,
            ip_address=ip_address,
            metadata={"email": new_user.email, "role": new_user.role, "name": new_user.name}
        )
        return new_user

    @staticmethod
    def update_user(
        db: Session,
        user_id: int,
        data: UserUpdateAdmin,
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> models.User:
        user = AdminService.get_user_details(db, user_id, current_user)

        # Org admin cannot modify a super admin
        if is_org_admin(current_user) and not is_super_admin(current_user):
            if normalize_role(user.role) == PlatformRole.SUPER_ADMIN:
                raise HTTPException(status_code=403, detail="Privilege escalation prevented: cannot modify Super Admin.")
            if data.organization_id is not None and data.organization_id != current_user.organization_id:
                raise HTTPException(status_code=403, detail="Cannot transfer user outside your organization.")

        changes = {}
        if data.name is not None:
            changes["old_name"] = user.name
            user.name = data.name.strip()
            changes["new_name"] = user.name

        if data.email is not None and data.email.strip().lower() != user.email:
            existing = db.query(models.User).filter(
                models.User.email == data.email.strip().lower(),
                models.User.id != user_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Email already taken.")
            changes["old_email"] = user.email
            user.email = data.email.strip().lower()
            changes["new_email"] = user.email

        if data.organization_id is not None and is_super_admin(current_user):
            changes["old_org_id"] = user.organization_id
            user.organization_id = data.organization_id
            changes["new_org_id"] = user.organization_id

        db.commit()
        db.refresh(user)

        AdminService.log_audit(
            db=db,
            action="user.update",
            entity_type="user",
            entity_id=str(user.id),
            actor_id=current_user.id,
            org_id=user.organization_id,
            ip_address=ip_address,
            metadata=changes
        )
        return user

    @staticmethod
    def update_user_role(
        db: Session,
        user_id: int,
        new_role: str,
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> models.User:
        """
        Change user role.
        Org Admin CANNOT assign Super Admin role or modify a Super Admin's role.
        """
        user = AdminService.get_user_details(db, user_id, current_user)
        target_role = normalize_role(new_role)

        if not is_super_admin(current_user):
            if target_role == PlatformRole.SUPER_ADMIN:
                raise HTTPException(status_code=403, detail="Privilege escalation prevented: cannot grant Super Admin role.")
            if normalize_role(user.role) == PlatformRole.SUPER_ADMIN:
                raise HTTPException(status_code=403, detail="Privilege escalation prevented: cannot alter Super Admin role.")

        old_role = user.role
        user.role = new_role
        db.commit()
        db.refresh(user)

        AdminService.log_audit(
            db=db,
            action="user.role_change",
            entity_type="user",
            entity_id=str(user.id),
            actor_id=current_user.id,
            org_id=user.organization_id,
            ip_address=ip_address,
            metadata={"old_role": old_role, "new_role": new_role}
        )
        return user

    @staticmethod
    def update_user_status(
        db: Session,
        user_id: int,
        is_active: Optional[bool] = None,
        is_suspended: Optional[bool] = None,
        reason: Optional[str] = None,
        current_user: Optional[models.User] = None,
        ip_address: Optional[str] = None
    ) -> models.User:
        """Activate, deactivate, suspend or unsuspend a user."""
        user = AdminService.get_user_details(db, user_id, current_user)

        if current_user and not is_super_admin(current_user):
            if normalize_role(user.role) == PlatformRole.SUPER_ADMIN:
                raise HTTPException(status_code=403, detail="Cannot alter status of Super Admin.")

        old_state = {"is_active": user.is_active, "is_suspended": user.is_suspended}
        if is_active is not None:
            user.is_active = is_active
        if is_suspended is not None:
            user.is_suspended = is_suspended

        db.commit()
        db.refresh(user)

        AdminService.log_audit(
            db=db,
            action="user.status_change",
            entity_type="user",
            entity_id=str(user.id),
            actor_id=current_user.id if current_user else None,
            org_id=user.organization_id,
            ip_address=ip_address,
            metadata={
                "reason": reason,
                "old_state": old_state,
                "new_state": {"is_active": user.is_active, "is_suspended": user.is_suspended}
            }
        )
        return user

    @staticmethod
    def reset_user_password(
        db: Session,
        user_id: int,
        new_password: Optional[str] = None,
        current_user: Optional[models.User] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Secure password reset workflow.
        Never exposes password hashes in audit logs or API outputs.
        """
        user = AdminService.get_user_details(db, user_id, current_user)

        if current_user and not is_super_admin(current_user):
            if normalize_role(user.role) == PlatformRole.SUPER_ADMIN:
                raise HTTPException(status_code=403, detail="Cannot reset password for Super Admin.")

        # Generate temporary password if not provided
        if not new_password:
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            new_password = "".join(secrets.choice(chars) for _ in range(12))

        user.password_hash = auth.get_password_hash(new_password)
        db.commit()

        # Audit log (NEVER include new_password or hash!)
        AdminService.log_audit(
            db=db,
            action="user.password_reset",
            entity_type="user",
            entity_id=str(user.id),
            actor_id=current_user.id if current_user else None,
            org_id=user.organization_id,
            ip_address=ip_address,
            metadata={"reset_by": current_user.email if current_user else "system"}
        )

        return {
            "user_id": user.id,
            "email": user.email,
            "temporary_password": new_password,
            "message": "Password reset successfully. Please share the temporary password with the user."
        }

    @staticmethod
    def get_user_activity(db: Session, user_id: int, current_user: models.User) -> List[Dict[str, Any]]:
        user = AdminService.get_user_details(db, user_id, current_user)
        logs = db.query(models.AuditLog).filter(
            or_(
                models.AuditLog.actor_id == user.id,
                and_(models.AuditLog.entity_type == "user", models.AuditLog.entity_id == str(user.id))
            )
        ).order_by(desc(models.AuditLog.created_at)).limit(50).all()

        results = []
        for l in logs:
            meta = None
            if l.metadata_json:
                try:
                    meta = json.loads(l.metadata_json)
                except Exception:
                    meta = {}
            results.append({
                "id": l.id,
                "action": l.action,
                "entity_type": l.entity_type,
                "entity_id": l.entity_id,
                "ip_address": l.ip_address,
                "metadata": meta,
                "created_at": l.created_at
            })
        return results

    @staticmethod
    def get_user_assessment_history(db: Session, user_id: int, current_user: models.User) -> List[Dict[str, Any]]:
        user = AdminService.get_user_details(db, user_id, current_user)
        sessions = db.query(models.ExamSession).options(joinedload(models.ExamSession.exam)).filter(
            models.ExamSession.student_id == user.id
        ).order_by(desc(models.ExamSession.id)).all()

        results = []
        for s in sessions:
            exam = s.exam
            res_rec = db.query(models.ExamResult).filter_by(exam_session_id=s.id).first()
            results.append({
                "session_id": s.id,
                "exam_id": s.exam_id,
                "exam_title": exam.title if exam else None,
                "status": s.status,
                "score": s.score,
                "percentage": res_rec.percentage if res_rec else None,
                "pass_fail_status": res_rec.pass_fail_status if res_rec else None,
                "integrity_score": s.integrity_score,
                "risk_level": s.risk_level,
                "started_at": s.started_at,
                "submitted_at": s.submitted_at
            })
        return results

    @staticmethod
    def bulk_import_users_csv(
        db: Session,
        csv_content: str,
        default_org_id: Optional[int],
        current_user: models.User,
        ip_address: Optional[str] = None
    ) -> BulkImportResult:
        """
        Parse and import users from CSV.
        Expected headers: email, name, role (optional), password (optional), organization_id (optional).
        Enforces tenant isolation and privilege escalation prevention.
        """
        f = io.StringIO(csv_content.strip())
        reader = csv.DictReader(f)

        total_processed = 0
        successful = 0
        failed = 0
        errors = []

        is_super = is_super_admin(current_user)

        for row_idx, row in enumerate(reader, start=2):
            total_processed += 1
            email = row.get("email", "").strip().lower()
            name = row.get("name", "").strip()
            role = row.get("role", "candidate").strip()
            password = row.get("password", "").strip()
            org_id_str = row.get("organization_id", "").strip()

            # Validation
            if not email or "@" not in email:
                failed += 1
                errors.append({"row": row_idx, "email": email, "reason": "Invalid or missing email address."})
                continue

            if not name:
                failed += 1
                errors.append({"row": row_idx, "email": email, "reason": "Missing user name."})
                continue

            norm_role = normalize_role(role)

            # Privilege escalation prevention
            if not is_super:
                if norm_role in (PlatformRole.SUPER_ADMIN, PlatformRole.ORG_ADMIN):
                    failed += 1
                    errors.append({"row": row_idx, "email": email, "reason": "Privilege escalation: Org Admin cannot import admin accounts."})
                    continue
                effective_org_id = current_user.organization_id
            else:
                effective_org_id = int(org_id_str) if org_id_str.isdigit() else default_org_id

            # Check duplicate email
            if db.query(models.User).filter(models.User.email == email).first():
                failed += 1
                errors.append({"row": row_idx, "email": email, "reason": "Email already exists in system."})
                continue

            if not password or len(password) < 8:
                password = secrets.token_urlsafe(10) + "A1!"

            try:
                new_u = models.User(
                    email=email,
                    name=name,
                    role=role,
                    password_hash=auth.get_password_hash(password),
                    organization_id=effective_org_id,
                    is_active=True,
                    is_suspended=False
                )
                db.add(new_u)
                db.commit()
                successful += 1
            except Exception as e:
                db.rollback()
                failed += 1
                errors.append({"row": row_idx, "email": email, "reason": str(e)})

        AdminService.log_audit(
            db=db,
            action="user.bulk_import",
            entity_type="user",
            actor_id=current_user.id,
            org_id=current_user.organization_id if not is_super else default_org_id,
            ip_address=ip_address,
            metadata={"processed": total_processed, "successful": successful, "failed": failed}
        )

        return BulkImportResult(
            total_processed=total_processed,
            successful_imports=successful,
            failed_imports=failed,
            errors=errors
        )

    # =========================================================================
    # 5. PLATFORM CONFIGURATION (SUPER ADMIN ONLY)
    # =========================================================================

    # Default platform configurations
    DEFAULT_PLATFORM_CONFIGS = {
        "platform_name": ("ExamProctor Platform", "string", "Public platform name displayed in UI and emails"),
        "default_timezone": ("UTC", "string", "Default server and display timezone"),
        "default_session_timeout_minutes": (60, "int", "Default candidate exam session timeout"),
        "max_upload_size_mb": (10, "int", "Maximum file upload limit in megabytes"),
        "allowed_file_formats": ("json,csv,png,jpg,pdf", "string", "Comma-separated allowed attachment extensions"),
        "password_policy_min_length": (8, "int", "Minimum user password length"),
        "rate_limit_per_minute": (60, "int", "Default API rate limit per minute"),
        "maintenance_mode": (False, "bool", "When true, candidates and examiners cannot access assessments"),
        "enable_proctoring": (True, "bool", "Global toggle for webcam, audio, and tab proctoring"),
        "enable_integrations": (True, "bool", "Global toggle for external webhook and LMS integrations")
    }

    @staticmethod
    def get_platform_configs(db: Session, current_user: models.User) -> Dict[str, Any]:
        if not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can access platform configurations.")

        rows = db.query(models.PlatformConfig).all()
        config_map = {r.key: r for r in rows}

        results = {}
        for key, (def_val, v_type, desc_str) in AdminService.DEFAULT_PLATFORM_CONFIGS.items():
            if key in config_map:
                r = config_map[key]
                val = r.value
                if r.value_type == "int":
                    try: val = int(val)
                    except: pass
                elif r.value_type == "bool":
                    val = (str(val).lower() in ("true", "1", "yes"))
                elif r.value_type == "json":
                    try: val = json.loads(val)
                    except: pass
                results[key] = {
                    "value": val,
                    "value_type": r.value_type,
                    "description": r.description or desc_str,
                    "is_sensitive": r.is_sensitive
                }
            else:
                results[key] = {
                    "value": def_val,
                    "value_type": v_type,
                    "description": desc_str,
                    "is_sensitive": False
                }
        return results

    @staticmethod
    def validate_platform_config(key: str, value: Any):
        """
        Strict security validation:
        Never allow disabling auth, authz, or tenant isolation.
        """
        k_lower = key.lower().strip()
        val_str = str(value).lower().strip()

        # Security check: forbidden overrides
        forbidden_keys = [
            "disable_auth", "disable_rbac", "bypass_tenant_isolation",
            "disable_tenant_isolation", "allow_insecure_auth", "no_auth"
        ]
        if any(f in k_lower for f in forbidden_keys):
            raise HTTPException(
                status_code=400,
                detail=f"Security violation: configuration '{key}' attempts to disable platform security controls."
            )

        if "timeout" in k_lower and isinstance(value, (int, float)) and value <= 0:
            raise HTTPException(status_code=400, detail="Timeout must be a positive integer.")

        if "min_length" in k_lower and isinstance(value, int) and value < 6:
            raise HTTPException(status_code=400, detail="Password min length cannot be less than 6.")

    @staticmethod
    def set_platform_config(
        db: Session,
        key: str,
        value: Any,
        value_type: str = "string",
        description: Optional[str] = None,
        current_user: Optional[models.User] = None,
        ip_address: Optional[str] = None
    ) -> models.PlatformConfig:
        if current_user and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can update platform configurations.")

        AdminService.validate_platform_config(key, value)

        stored_val = json.dumps(value) if value_type == "json" else str(value)

        item = db.query(models.PlatformConfig).filter(models.PlatformConfig.key == key).first()
        if not item:
            item = models.PlatformConfig(
                key=key,
                value=stored_val,
                value_type=value_type,
                description=description,
                updated_by=current_user.id if current_user else None,
                created_at=utc_now(),
                updated_at=utc_now()
            )
            db.add(item)
        else:
            item.value = stored_val
            item.value_type = value_type
            if description:
                item.description = description
            item.updated_by = current_user.id if current_user else None
            item.updated_at = utc_now()

        db.commit()
        db.refresh(item)

        if key == "maintenance_mode":
            try:
                from core.maintenance import invalidate_maintenance_cache
                invalidate_maintenance_cache()
            except Exception:
                pass

        AdminService.log_audit(
            db=db,
            action="platform_config.update",
            entity_type="config",
            entity_id=key,
            actor_id=current_user.id if current_user else None,
            ip_address=ip_address,
            metadata={"key": key, "value": stored_val, "value_type": value_type}
        )
        return item

    # =========================================================================
    # 6. ORGANIZATION CONFIGURATION
    # =========================================================================

    DEFAULT_ORG_CONFIGS = {
        "branding_name": ("ExamProctor", "string"),
        "branding_logo_url": ("", "string"),
        "default_duration_minutes": (60, "int"),
        "default_pass_percentage": (40.0, "float"),
        "allowed_assessment_types": ("academic,placement,technical,custom", "string"),
        "user_registration_policy": ("invite_only", "string"),  # open, invite_only, closed
        "default_max_attempts": (1, "int"),
        "allow_backtracking": (True, "bool")
    }

    @staticmethod
    def get_org_configs(db: Session, org_id: int, current_user: models.User) -> Dict[str, Any]:
        AdminService.get_organization(db, org_id, current_user)
        rows = db.query(models.OrganizationConfig).filter(models.OrganizationConfig.organization_id == org_id).all()
        config_map = {r.key: r for r in rows}

        results = {}
        for key, (def_val, v_type) in AdminService.DEFAULT_ORG_CONFIGS.items():
            if key in config_map:
                r = config_map[key]
                val = r.value
                if r.value_type == "int":
                    try: val = int(val)
                    except: pass
                elif r.value_type == "float":
                    try: val = float(val)
                    except: pass
                elif r.value_type == "bool":
                    val = (str(val).lower() in ("true", "1", "yes"))
                elif r.value_type == "json":
                    try: val = json.loads(val)
                    except: pass
                results[key] = {"value": val, "value_type": r.value_type}
            else:
                results[key] = {"value": def_val, "value_type": v_type}
        return results

    @staticmethod
    def set_org_config(
        db: Session,
        org_id: int,
        key: str,
        value: Any,
        value_type: str = "string",
        current_user: Optional[models.User] = None,
        ip_address: Optional[str] = None
    ) -> models.OrganizationConfig:
        AdminService.get_organization(db, org_id, current_user)

        # Check permissions: Super Admin or Org Admin of this org
        if current_user and not is_super_admin(current_user):
            if not (is_org_admin(current_user) and current_user.organization_id == org_id):
                raise HTTPException(status_code=403, detail="Not authorized to configure this organization.")

        # Validation: organization config cannot override mandatory platform restrictions
        k_lower = key.lower().strip()
        forbidden_org_keys = ["disable_auth", "bypass_proctoring_mandatory", "disable_rbac"]
        if any(f in k_lower for f in forbidden_org_keys):
            raise HTTPException(status_code=400, detail="Cannot override mandatory platform security policies.")

        stored_val = json.dumps(value) if value_type == "json" else str(value)

        item = db.query(models.OrganizationConfig).filter(
            models.OrganizationConfig.organization_id == org_id,
            models.OrganizationConfig.key == key
        ).first()

        if not item:
            item = models.OrganizationConfig(
                organization_id=org_id,
                key=key,
                value=stored_val,
                value_type=value_type,
                updated_by=current_user.id if current_user else None,
                created_at=utc_now(),
                updated_at=utc_now()
            )
            db.add(item)
        else:
            item.value = stored_val
            item.value_type = value_type
            item.updated_by = current_user.id if current_user else None
            item.updated_at = utc_now()

        db.commit()
        db.refresh(item)

        if key == "maintenance_mode":
            try:
                from core.maintenance import invalidate_maintenance_cache
                invalidate_maintenance_cache()
            except Exception:
                pass

        AdminService.log_audit(
            db=db,
            action="org_config.update",
            entity_type="organization_config",
            entity_id=f"{org_id}:{key}",
            actor_id=current_user.id if current_user else None,
            org_id=org_id,
            ip_address=ip_address,
            metadata={"key": key, "value": stored_val}
        )
        return item
