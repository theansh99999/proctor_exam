"""
modules/admin/router.py
-----------------------
Versioned REST APIs under /api/v1/admin/ for Phase 10:
Platform Administration & System Configuration.
Enforces strict RBAC, tenant isolation, and privilege escalation prevention.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

import database
import models
from auth import (
    require_auth_api,
    require_org_admin_api,
    require_super_admin_api
)
from modules.admin.service import AdminService
from modules.admin.schemas import (
    OrganizationCreateAdmin,
    OrganizationUpdateAdmin,
    OrganizationStatusUpdate,
    AssignAdminRequest,
    OrganizationOutAdmin,
    UserCreateAdmin,
    UserUpdateAdmin,
    UserRoleUpdate,
    UserStatusUpdate,
    UserPasswordReset,
    UserOutAdmin,
    PlatformConfigItem,
    PlatformConfigUpdateBatch,
    OrgConfigItem,
    OrgConfigUpdateBatch,
    AuditLogOut,
    SuperAdminDashboardOut,
    ActivityMonitoringOut,
    BulkImportResult
)

router = APIRouter(tags=["Platform Administration"])


def get_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# =============================================================================
# 1. SUPER ADMIN DASHBOARD & ACTIVITY
# =============================================================================

@router.get("/dashboard", response_model=SuperAdminDashboardOut)
def get_super_admin_dashboard_endpoint(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_api)
):
    """Centralized platform dashboard for Super Admin."""
    return AdminService.get_super_admin_dashboard(db, current_user)


@router.get("/activity", response_model=ActivityMonitoringOut)
def get_activity_monitoring_endpoint(
    org_id: Optional[int] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Administrative activity monitoring (recent logs, failures summary)."""
    return AdminService.get_activity_monitoring(db, current_user, org_id=org_id)


# =============================================================================
# 2. AUDIT LOGS (APPEND-ONLY SEARCH)
# =============================================================================

@router.get("/audit-logs", response_model=List[AuditLogOut])
def get_audit_logs_endpoint(
    org_id: Optional[int] = Query(None),
    actor_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Search audit logs with RBAC and organization scoping."""
    return AdminService.get_audit_logs(
        db=db,
        current_user=current_user,
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        limit=limit,
        offset=offset
    )


# =============================================================================
# 3. ORGANIZATION MANAGEMENT
# =============================================================================

@router.get("/organizations", response_model=List[OrganizationOutAdmin])
def list_organizations_endpoint(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """List organizations. Super Admin sees all; Org Admin sees own."""
    return AdminService.list_organizations(db, current_user, status_filter=status, search=search)


@router.post("/organizations", response_model=OrganizationOutAdmin, status_code=status.HTTP_201_CREATED)
def create_organization_endpoint(
    data: OrganizationCreateAdmin,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_api)
):
    """Create a new organization (Super Admin only)."""
    return AdminService.create_organization(
        db=db,
        data=data,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )


@router.get("/organizations/{org_id}", response_model=OrganizationOutAdmin)
def get_organization_endpoint(
    org_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get organization details."""
    org = AdminService.get_organization(db, org_id, current_user)
    u_count = db.query(models.User).filter(models.User.organization_id == org.id).count()
    e_count = db.query(models.Exam).filter(models.Exam.organization_id == org.id).count()
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "is_active": bool(org.is_active),
        "is_suspended": bool(org.is_suspended),
        "created_at": org.created_at,
        "updated_at": org.updated_at,
        "total_users": u_count,
        "total_exams": e_count
    }


@router.put("/organizations/{org_id}", response_model=OrganizationOutAdmin)
def update_organization_endpoint(
    org_id: int,
    data: OrganizationUpdateAdmin,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Update organization details."""
    org = AdminService.update_organization(
        db=db,
        org_id=org_id,
        data=data,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )
    u_count = db.query(models.User).filter(models.User.organization_id == org.id).count()
    e_count = db.query(models.Exam).filter(models.Exam.organization_id == org.id).count()
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "is_active": bool(org.is_active),
        "is_suspended": bool(org.is_suspended),
        "created_at": org.created_at,
        "updated_at": org.updated_at,
        "total_users": u_count,
        "total_exams": e_count
    }


@router.post("/organizations/{org_id}/status")
def update_organization_status_endpoint(
    org_id: int,
    data: OrganizationStatusUpdate,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_api)
):
    """Lifecycle state update: activate, deactivate, suspend, reactivate (Super Admin only)."""
    org = AdminService.update_organization_status(
        db=db,
        org_id=org_id,
        action=data.action,
        current_user=current_user,
        reason=data.reason,
        ip_address=get_client_ip(request)
    )
    return {
        "message": f"Organization status updated to '{data.action}'.",
        "org_id": org.id,
        "is_active": org.is_active,
        "is_suspended": org.is_suspended
    }


@router.post("/organizations/{org_id}/assign-admin")
def assign_org_admin_endpoint(
    org_id: int,
    data: AssignAdminRequest,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Assign user as Organization Admin."""
    user = AdminService.assign_org_admin(
        db=db,
        org_id=org_id,
        user_id=data.user_id,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )
    return {"message": "Admin assigned successfully.", "user_id": user.id, "email": user.email, "role": user.role}


@router.get("/organizations/{org_id}/users", response_model=List[UserOutAdmin])
def get_org_users_endpoint(
    org_id: int,
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get all users of an organization."""
    users = AdminService.get_org_users(db, org_id, current_user, role=role, status_filter=status)
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "organization_id": u.organization_id,
            "is_active": getattr(u, "is_active", True),
            "is_suspended": getattr(u, "is_suspended", False)
        }
        for u in users
    ]


@router.get("/organizations/{org_id}/assessments")
def get_org_assessments_endpoint(
    org_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get all assessments of an organization."""
    exams = AdminService.get_org_assessments(db, org_id, current_user)
    return [
        {
            "id": e.id,
            "title": e.title,
            "assessment_type": e.assessment_type,
            "status": e.status,
            "max_attempts": e.max_attempts,
            "duration_minutes": e.duration_minutes
        }
        for e in exams
    ]


@router.get("/organizations/{org_id}/activity")
def get_org_activity_endpoint(
    org_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get organization activity history."""
    return AdminService.get_org_activity(db, org_id, current_user)


@router.get("/organizations/{org_id}/analytics")
def get_org_analytics_endpoint(
    org_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get organization performance and assessment metrics."""
    return AdminService.get_org_analytics(db, org_id, current_user)


# =============================================================================
# 4. USER ADMINISTRATION
# =============================================================================

@router.get("/users", response_model=List[UserOutAdmin])
def list_users_endpoint(
    org_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """List users with filters (role, status, org, search)."""
    return AdminService.list_users(
        db=db,
        current_user=current_user,
        org_id=org_id,
        role=role,
        status_filter=status,
        search=search,
        limit=limit,
        offset=offset
    )


@router.post("/users", response_model=UserOutAdmin, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
    data: UserCreateAdmin,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Create user with privilege escalation prevention."""
    user = AdminService.create_user(
        db=db,
        data=data,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "organization_id": user.organization_id,
        "is_active": getattr(user, "is_active", True),
        "is_suspended": getattr(user, "is_suspended", False)
    }


@router.get("/users/{user_id}", response_model=UserOutAdmin)
def get_user_details_endpoint(
    user_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get user details."""
    user = AdminService.get_user_details(db, user_id, current_user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "organization_id": user.organization_id,
        "organization_name": user.organization.name if user.organization else None,
        "is_active": getattr(user, "is_active", True),
        "is_suspended": getattr(user, "is_suspended", False)
    }


@router.put("/users/{user_id}", response_model=UserOutAdmin)
def update_user_endpoint(
    user_id: int,
    data: UserUpdateAdmin,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Update user information."""
    user = AdminService.update_user(
        db=db,
        user_id=user_id,
        data=data,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "organization_id": user.organization_id,
        "is_active": getattr(user, "is_active", True),
        "is_suspended": getattr(user, "is_suspended", False)
    }


@router.post("/users/{user_id}/role")
def update_user_role_endpoint(
    user_id: int,
    data: UserRoleUpdate,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Change user role with privilege escalation prevention."""
    user = AdminService.update_user_role(
        db=db,
        user_id=user_id,
        new_role=data.role,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )
    return {"message": "User role updated successfully.", "user_id": user.id, "new_role": user.role}


@router.post("/users/{user_id}/status")
def update_user_status_endpoint(
    user_id: int,
    data: UserStatusUpdate,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Activate, deactivate, suspend or unsuspend a user."""
    user = AdminService.update_user_status(
        db=db,
        user_id=user_id,
        is_active=data.is_active,
        is_suspended=data.is_suspended,
        reason=data.reason,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )
    return {
        "message": "User status updated successfully.",
        "user_id": user.id,
        "is_active": user.is_active,
        "is_suspended": user.is_suspended
    }


@router.post("/users/{user_id}/reset-password")
def reset_user_password_endpoint(
    user_id: int,
    data: Optional[UserPasswordReset] = None,
    request: Request = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Secure password reset workflow."""
    new_pw = data.new_password if data else None
    return AdminService.reset_user_password(
        db=db,
        user_id=user_id,
        new_password=new_pw,
        current_user=current_user,
        ip_address=get_client_ip(request) if request else None
    )


@router.get("/users/{user_id}/activity")
def get_user_activity_endpoint(
    user_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get audit activity history for a specific user."""
    return AdminService.get_user_activity(db, user_id, current_user)


@router.get("/users/{user_id}/assessment-history")
def get_user_assessment_history_endpoint(
    user_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get assessment attempt history for a specific user."""
    return AdminService.get_user_assessment_history(db, user_id, current_user)


@router.post("/users/bulk-import", response_model=BulkImportResult)
async def bulk_import_users_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    csv_text: Optional[str] = Form(None),
    default_org_id: Optional[int] = Form(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Bulk import users via CSV file or raw CSV text."""
    content = ""
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8", errors="replace")
    elif csv_text:
        content = csv_text
    else:
        # Check if json body has csv_content
        try:
            body = await request.json()
            content = body.get("csv_content", "")
            if body.get("default_org_id"):
                default_org_id = body.get("default_org_id")
        except Exception:
            pass

    if not content.strip():
        raise HTTPException(status_code=400, detail="No CSV content provided.")

    return AdminService.bulk_import_users_csv(
        db=db,
        csv_content=content,
        default_org_id=default_org_id,
        current_user=current_user,
        ip_address=get_client_ip(request)
    )


# =============================================================================
# 5. PLATFORM CONFIGURATION (SUPER ADMIN ONLY)
# =============================================================================

@router.get("/platform/config")
def get_platform_config_endpoint(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_api)
):
    """Get all platform configuration parameters."""
    return AdminService.get_platform_configs(db, current_user)


@router.put("/platform/config")
def update_platform_config_endpoint(
    data: PlatformConfigUpdateBatch,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_api)
):
    """Update platform configuration parameters."""
    updated = {}
    for key, val in data.configs.items():
        v_type = "string"
        if isinstance(val, bool): v_type = "bool"
        elif isinstance(val, int): v_type = "int"
        elif isinstance(val, float): v_type = "float"
        elif isinstance(val, (dict, list)): v_type = "json"

        item = AdminService.set_platform_config(
            db=db,
            key=key,
            value=val,
            value_type=v_type,
            current_user=current_user,
            ip_address=get_client_ip(request)
        )
        updated[key] = val
    return {"message": "Platform configurations updated.", "updated": updated}


# =============================================================================
# 6. ORGANIZATION CONFIGURATION
# =============================================================================

@router.get("/organizations/{org_id}/config")
def get_org_config_endpoint(
    org_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Get configuration parameters for an organization."""
    return AdminService.get_org_configs(db, org_id, current_user)


@router.put("/organizations/{org_id}/config")
def update_org_config_endpoint(
    org_id: int,
    data: OrgConfigUpdateBatch,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_org_admin_api)
):
    """Update configuration parameters for an organization."""
    updated = {}
    for key, val in data.configs.items():
        v_type = "string"
        if isinstance(val, bool): v_type = "bool"
        elif isinstance(val, int): v_type = "int"
        elif isinstance(val, float): v_type = "float"
        elif isinstance(val, (dict, list)): v_type = "json"

        AdminService.set_org_config(
            db=db,
            org_id=org_id,
            key=key,
            value=val,
            value_type=v_type,
            current_user=current_user,
            ip_address=get_client_ip(request)
        )
        updated[key] = val
    return {"message": "Organization configurations updated.", "updated": updated}
