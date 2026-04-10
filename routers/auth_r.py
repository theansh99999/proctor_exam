from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import models, schemas, auth, database
from datetime import timedelta

router = APIRouter(tags=["UI Auth"])
templates = Jinja2Templates(directory="templates")

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="auth/login.html", context={})

@router.post("/login")
def login_submit(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.password_hash):
        return RedirectResponse(url="/login?error=Invalid Credentials", status_code=status.HTTP_302_FOUND)
    
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.email, "role": user.role}, expires_delta=access_token_expires
    )
    
    # Check role and redirect
    redirect_url = "/teacher/dashboard" if user.role == "teacher" else "/student/dashboard"
    res = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    
    # Set HTTPOnly Cookie
    res.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return res

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="auth/register.html", context={})

@router.post("/register")
def register_submit(
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(database.get_db)
):
    # Check if user exists
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
         return RedirectResponse(url="/register?error=Email already registered", status_code=status.HTTP_302_FOUND)
    
    # For students, they can only register if a teacher has added their email to a group?
    # Actually, let's allow anyone to register, but they won't see exams unless added to a group.
    new_user = models.User(
        email=email,
        password_hash=auth.get_password_hash(password),
        name=name,
        role=role
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/login?msg=Registered successfully", status_code=status.HTTP_302_FOUND)

@router.get("/logout")
def logout():
    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    res.delete_cookie("access_token")
    return res

@router.get("/profile", response_class=HTMLResponse)
def user_profile(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_auth)):
    return templates.TemplateResponse(request=request, name="auth/profile.html", context={"user": current_user})

@router.get("/settings", response_class=HTMLResponse)
def user_settings(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_auth)):
    return templates.TemplateResponse(request=request, name="auth/settings.html", context={"user": current_user})

@router.post("/settings")
def update_settings(
    name: str = Form(...),
    password: str = Form(""),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth)
):
    current_user.name = name
    if password.strip():
        current_user.password_hash = auth.get_password_hash(password)
    db.commit()
    return RedirectResponse(url="/settings?msg=updated", status_code=302)
