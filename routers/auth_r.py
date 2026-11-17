from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, Response

from fastapi.templating import Jinja2Templates

from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy.orm import Session

from typing import Optional

import models, schemas, auth, database

from datetime import timedelta

import csrf as csrf_module

from limiter import limiter

from core.rbac import is_examiner_or_admin, is_super_admin

from modules.admin.service import AdminService



router = APIRouter(tags=["UI Auth"])

templates = Jinja2Templates(directory="templates")



# ── Allowed roles that can self-register via public form ───────────────────────

# Teachers/Examiners must be created by an existing admin/teacher — not via public form.

ALLOWED_SELF_REGISTER_ROLES = {"student", "candidate"}



# ── Login ──────────────────────────────────────────────────────────────────────



@router.get("/login", response_class=HTMLResponse)

def login_page(request: Request):

    csrf_token = csrf_module.generate_csrf_token(request)

    return templates.TemplateResponse(

        request=request, name="auth/login.html",

        context={"csrf_token": csrf_token}

    )



def _get_client_ip(req: Request) -> Optional[str]:

    f = req.headers.get("X-Forwarded-For")

    if f:

        return f.split(",")[0].strip()

    return req.client.host if req.client else None



@router.post("/login")

@limiter.limit("15/minute")

def login_submit(

    request: Request,

    response: Response,

    email: str = Form(...),

    password: str = Form(...),

    csrf_token: Optional[str] = Form(None),

    db: Session = Depends(database.get_db)

):

    # CSRF verification: missing or invalid token raises HTTP 403

    csrf_module.csrf_protect(request, csrf_token)

    client_ip = _get_client_ip(request)



    user = db.query(models.User).filter(models.User.email == email).first()

    if not user or not auth.verify_password(password, user.password_hash):

        try:

            AdminService.log_audit(

                db=db,

                action="auth.login_failed",

                entity_type="auth",

                entity_id=email,

                ip_address=client_ip,

                metadata={"reason": "invalid_credentials", "attempted_email": email}

            )

        except Exception:

            pass

        new_csrf = csrf_module.generate_csrf_token(request)

        return templates.TemplateResponse(

            request=request, name="auth/login.html",

            context={"error": "Invalid email or password.", "csrf_token": new_csrf},

            status_code=200

        )



    # Check user suspended or inactive

    if getattr(user, "is_suspended", False) or not getattr(user, "is_active", True):

        try:

            AdminService.log_audit(

                db=db,

                action="auth.login_failed",

                entity_type="auth",

                entity_id=str(user.id),

                actor_id=user.id,

                org_id=user.organization_id,

                ip_address=client_ip,

                metadata={"reason": "account_suspended_or_inactive", "email": user.email}

            )

        except Exception:

            pass

        new_csrf = csrf_module.generate_csrf_token(request)

        return templates.TemplateResponse(

            request=request, name="auth/login.html",

            context={"error": "Your account has been suspended or deactivated. Please contact support.", "csrf_token": new_csrf},

            status_code=200

        )



    # Check organization suspended or inactive (unless super_admin)

    if not is_super_admin(user) and user.organization_id:

        org = db.query(models.Organization).filter(models.Organization.id == user.organization_id).first()

        if org and (getattr(org, "is_suspended", False) or not getattr(org, "is_active", True)):

            try:

                AdminService.log_audit(

                    db=db,

                    action="auth.login_failed",

                    entity_type="auth",

                    entity_id=str(user.id),

                    actor_id=user.id,

                    org_id=org.id,

                    ip_address=client_ip,

                    metadata={"reason": "org_suspended_or_inactive", "org_id": org.id, "email": user.email}

                )

            except Exception:

                pass

            new_csrf = csrf_module.generate_csrf_token(request)

            return templates.TemplateResponse(

                request=request, name="auth/login.html",

                context={"error": "Your organization is currently deactivated or suspended. Access restricted.", "csrf_token": new_csrf},

                status_code=200

            )



    # Successful login audit

    try:

        AdminService.log_audit(

            db=db,

            action="auth.login",

            entity_type="auth",

            entity_id=str(user.id),

            actor_id=user.id,

            org_id=user.organization_id,

            ip_address=client_ip,

            metadata={"email": user.email, "role": user.role}

        )

    except Exception:

        pass



    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)

    access_token = auth.create_access_token(

        data={"sub": user.email, "role": user.role}, expires_delta=access_token_expires

    )



    # Route Super Admin to admin dashboard, Examiner/Teacher to teacher dashboard, Candidate/Student to student dashboard

    if is_super_admin(user):

        redirect_url = "/admin/dashboard"

    elif is_examiner_or_admin(user):

        redirect_url = "/teacher/dashboard"

    else:

        redirect_url = "/student/dashboard"



    res = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    res.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True, samesite="lax")

    return res





# ── Register ───────────────────────────────────────────────────────────────────



@router.get("/register", response_class=HTMLResponse)

def register_page(request: Request):

    csrf_token = csrf_module.generate_csrf_token(request)

    return templates.TemplateResponse(

        request=request, name="auth/register.html",

        context={"csrf_token": csrf_token}

    )



@router.post("/register")

@limiter.limit("10/minute")

def register_submit(

    request: Request,

    email: str = Form(...),

    password: str = Form(...),

    name: str = Form(...),

    role: str = Form(...),

    csrf_token: Optional[str] = Form(None),

    db: Session = Depends(database.get_db)

):

    # ── CSRF check: missing or invalid token raises HTTP 403 ─────────────────

    csrf_module.csrf_protect(request, csrf_token)



    # ── Role validation: only 'student' allowed via public form ─────────────

    if role not in ALLOWED_SELF_REGISTER_ROLES:

        new_csrf = csrf_module.generate_csrf_token(request)

        return templates.TemplateResponse(

            request=request, name="auth/register.html",

            context={

                "error": "Public registration is only available for students. Contact your teacher to get a teacher account.",

                "csrf_token": new_csrf

            },

            status_code=200

        )



    # ── Password strength: minimum 8 characters ─────────────────────────────

    if len(password) < 8:

        new_csrf = csrf_module.generate_csrf_token(request)

        return templates.TemplateResponse(

            request=request, name="auth/register.html",

            context={"error": "Password must be at least 8 characters long.", "csrf_token": new_csrf},

            status_code=200

        )



    # ── Duplicate email check ────────────────────────────────────────────────

    existing = db.query(models.User).filter(models.User.email == email).first()

    if existing:

        new_csrf = csrf_module.generate_csrf_token(request)

        return templates.TemplateResponse(

            request=request, name="auth/register.html",

            context={"error": "Email is already registered.", "csrf_token": new_csrf},

            status_code=200

        )



    new_user = models.User(

        email=email,

        password_hash=auth.get_password_hash(password),

        name=name,

        role="student"  # Always force 'student' regardless of form value

    )

    db.add(new_user)

    db.commit()

    return RedirectResponse(url="/login?msg=Registered+successfully", status_code=status.HTTP_302_FOUND)





# ── Dashboard redirect ─────────────────────────────────────────────────────────



@router.get("/dashboard")

def redirect_dashboard(current_user: models.User = Depends(auth.require_auth)):

    if is_examiner_or_admin(current_user):

        return RedirectResponse(url="/teacher/dashboard", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/student/dashboard", status_code=status.HTTP_302_FOUND)





# ── Logout ─────────────────────────────────────────────────────────────────────



@router.get("/logout")

def logout(request: Request, db: Session = Depends(database.get_db)):

    try:

        user = auth.get_current_user_cookie(request, db)

        if user:

            AdminService.log_audit(

                db=db,

                action="auth.logout",

                entity_type="auth",

                entity_id=str(user.id),

                actor_id=user.id,

                org_id=user.organization_id,

                ip_address=request.client.host if request.client else None,

                metadata={"email": user.email}

            )

    except Exception:

        pass

    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    res.delete_cookie("access_token")

    return res





# ── Profile ────────────────────────────────────────────────────────────────────



@router.get("/profile", response_class=HTMLResponse)

def user_profile(

    request: Request,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth)

):

    return templates.TemplateResponse(

        request=request, name="auth/profile.html",

        context={"user": current_user}

    )





# ── Settings ───────────────────────────────────────────────────────────────────



@router.get("/settings", response_class=HTMLResponse)

def user_settings(

    request: Request,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth)

):

    csrf_token = csrf_module.generate_csrf_token(request)

    return templates.TemplateResponse(

        request=request, name="auth/settings.html",

        context={"user": current_user, "csrf_token": csrf_token}

    )



@router.post("/settings")

def update_settings(

    request: Request,

    name: str = Form(...),

    current_password: str = Form(""),

    password: str = Form(""),

    csrf_token: Optional[str] = Form(None),

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth)

):

    # ── CSRF check ──────────────────────────────────────────────────────────

    csrf_module.csrf_protect(request, csrf_token)



    current_user.name = name.strip()



    # ── Password change requires current password verification ───────────────

    if password.strip():

        if not current_password.strip():

            csrf_token_new = csrf_module.generate_csrf_token(request)

            return templates.TemplateResponse(

                request=request, name="auth/settings.html",

                context={

                    "user": current_user,

                    "error": "Current password is required to set a new password.",

                    "csrf_token": csrf_token_new

                },

                status_code=200

            )

        if not auth.verify_password(current_password, current_user.password_hash):

            csrf_token_new = csrf_module.generate_csrf_token(request)

            return templates.TemplateResponse(

                request=request, name="auth/settings.html",

                context={

                    "user": current_user,

                    "error": "Current password is incorrect.",

                    "csrf_token": csrf_token_new

                },

                status_code=200

            )

        if len(password.strip()) < 8:

            csrf_token_new = csrf_module.generate_csrf_token(request)

            return templates.TemplateResponse(

                request=request, name="auth/settings.html",

                context={

                    "user": current_user,

                    "error": "New password must be at least 8 characters long.",

                    "csrf_token": csrf_token_new

                },

                status_code=200

            )

        current_user.password_hash = auth.get_password_hash(password.strip())



    db.commit()

    return RedirectResponse(url="/settings?msg=updated", status_code=302)





# =============================================================================

# PHASE 9: NOTIFICATION CENTER & PREFERENCES UI

# =============================================================================



@router.get("/notifications", response_class=HTMLResponse)

def notification_center_page(

    request: Request,

    category: Optional[str] = None,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth)

):

    from modules.notifications.service import NotificationService

    notifs, _, _ = NotificationService.list_notifications(

        db=db,

        current_user=current_user,

        category=category,

        page=1,

        page_size=100

    )

    return templates.TemplateResponse(

        request=request,

        name="notifications/index.html",

        context={

            "user": current_user,

            "notifications": notifs,

            "selected_category": category

        }

    )





@router.get("/notifications/preferences", response_class=HTMLResponse)

def notification_preferences_page(

    request: Request,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth)

):

    from modules.notifications.service import NotificationService

    pref = NotificationService.get_or_create_preferences(db, current_user.id, current_user.organization_id)

    message = request.query_params.get("message")

    return templates.TemplateResponse(

        request=request,

        name="notifications/preferences.html",

        context={

            "user": current_user,

            "preferences": pref,

            "message": message

        }

    )





@router.post("/notifications/preferences")

def handle_notification_preferences_submit(

    request: Request,

    in_app_enabled: Optional[str] = Form(None),

    email_enabled: Optional[str] = Form(None),

    reminders_enabled: Optional[str] = Form(None),

    results_enabled: Optional[str] = Form(None),

    announcements_enabled: Optional[str] = Form(None),

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth)

):

    from modules.notifications.service import NotificationService

    from modules.notifications.schemas import NotificationPreferenceUpdate



    update_data = NotificationPreferenceUpdate(

        in_app_enabled=(in_app_enabled is not None),

        email_enabled=(email_enabled is not None),

        reminders_enabled=(reminders_enabled is not None),

        results_enabled=(results_enabled is not None),

        announcements_enabled=(announcements_enabled is not None)

    )

    NotificationService.update_preferences(db, current_user.id, update_data, current_user)

    return RedirectResponse(url="/notifications/preferences?message=Preferences+saved+successfully!", status_code=302)
