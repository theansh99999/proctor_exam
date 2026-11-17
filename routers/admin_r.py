"""
routers/admin_r.py
------------------
HTML UI Routes for Phase 10: Platform Administration & System Configuration.
"""
from fastapi import APIRouter, Request, Depends, HTTPException, status, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional

import database
import models
import auth
from core.rbac import is_super_admin, is_org_admin
from modules.admin.service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin UI"])
templates = Jinja2Templates(directory="templates")


def require_admin_ui(request: Request, db: Session = Depends(database.get_db)) -> models.User:
    user = auth.require_auth(request, db)
    if not is_org_admin(user) and not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Admin authorization required.")
    return user


def require_super_admin_ui(request: Request, db: Session = Depends(database.get_db)) -> models.User:
    user = auth.require_auth(request, db)
    if not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Super Admin authorization required.")
    return user


# ── Super Admin Dashboard ──────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_ui)
):
    stats = AdminService.get_super_admin_dashboard(db, current_user)
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "user": current_user,
            "is_super_admin": True,
            "stats": stats
        }
    )


# ── Organizations Management ───────────────────────────────────────────────────

@router.get("/organizations", response_class=HTMLResponse)
def admin_organizations(
    request: Request,
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_ui)
):
    orgs = AdminService.list_organizations(db, current_user, status_filter=status, search=search)
    return templates.TemplateResponse(
        request=request,
        name="admin/organizations.html",
        context={
            "user": current_user,
            "is_super_admin": is_super_admin(current_user),
            "orgs": orgs,
            "status_filter": status,
            "search": search
        }
    )


# ── User Administration ────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    org_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_ui)
):
    users = AdminService.list_users(
        db=db,
        current_user=current_user,
        org_id=org_id,
        role=role,
        status_filter=status,
        search=search,
        limit=200
    )
    org_list = db.query(models.Organization).order_by(models.Organization.name).all() if is_super_admin(current_user) else []

    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "user": current_user,
            "is_super_admin": is_super_admin(current_user),
            "users": users,
            "org_list": org_list,
            "current_org_id": org_id,
            "role_filter": role,
            "status_filter": status,
            "search": search
        }
    )


# ── Platform Configuration ─────────────────────────────────────────────────────

@router.get("/settings/platform", response_class=HTMLResponse)
def admin_platform_settings(
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_super_admin_ui)
):
    configs = AdminService.get_platform_configs(db, current_user)
    return templates.TemplateResponse(
        request=request,
        name="admin/platform_settings.html",
        context={
            "user": current_user,
            "is_super_admin": True,
            "configs": configs
        }
    )


# ── Organization Configuration ─────────────────────────────────────────────────

@router.get("/settings/org", response_class=HTMLResponse)
def admin_org_settings(
    request: Request,
    org_id: Optional[int] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_ui)
):
    target_org_id = org_id or current_user.organization_id
    if not target_org_id:
        raise HTTPException(status_code=400, detail="Organization ID required.")

    org = AdminService.get_organization(db, target_org_id, current_user)
    configs = AdminService.get_org_configs(db, target_org_id, current_user)

    return templates.TemplateResponse(
        request=request,
        name="admin/org_settings.html",
        context={
            "user": current_user,
            "is_super_admin": is_super_admin(current_user),
            "org": org,
            "configs": configs
        }
    )


# ── Audit Trail ────────────────────────────────────────────────────────────────

@router.get("/audit-logs", response_class=HTMLResponse)
def admin_audit_logs(
    request: Request,
    org_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_ui)
):
    logs = AdminService.get_audit_logs(
        db=db,
        current_user=current_user,
        org_id=org_id,
        action=action,
        entity_type=entity_type,
        limit=100
    )
    org_list = db.query(models.Organization).order_by(models.Organization.name).all() if is_super_admin(current_user) else []

    return templates.TemplateResponse(
        request=request,
        name="admin/audit_logs.html",
        context={
            "user": current_user,
            "is_super_admin": is_super_admin(current_user),
            "logs": logs,
            "org_list": org_list,
            "current_org_id": org_id,
            "action_filter": action,
            "entity_filter": entity_type
        }
    )


# ── Activity Monitoring ────────────────────────────────────────────────────────

@router.get("/activity", response_class=HTMLResponse)
def admin_activity(
    request: Request,
    org_id: Optional[int] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_ui)
):
    data = AdminService.get_activity_monitoring(db, current_user, org_id=org_id)
    return templates.TemplateResponse(
        request=request,
        name="admin/activity.html",
        context={
            "user": current_user,
            "is_super_admin": is_super_admin(current_user),
            "data": data
        }
    )
