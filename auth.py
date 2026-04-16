from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import os
import models
import database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if os.getenv("ENV", "development").lower() == "production":
        raise Exception("CRITICAL: SECRET_KEY environment variable is not set in production!")
    print("WARNING: No SECRET_KEY set. Using default insecure key for development.")
    SECRET_KEY = "supersecretkey"
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user_from_token(token: str, db: Session):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        if not token:
            raise credentials_exception
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_user_api(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    return get_current_user_from_token(token, db)

def get_current_user_cookie(request: Request, db: Session = Depends(database.get_db)):
    token = request.cookies.get("access_token")
    if token and token.startswith("Bearer "):
        token = token.split(" ")[1]
    
    if not token:
        return None
    try:
        return get_current_user_from_token(token, db)
    except Exception:
        return None

def require_auth(request: Request, db: Session = Depends(database.get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user

def require_teacher(request: Request, db: Session = Depends(database.get_db)):
    user = require_auth(request, db)
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Not authorized as teacher")
    return user

def require_student(request: Request, db: Session = Depends(database.get_db)):
    user = require_auth(request, db)
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Not authorized as student")
    return user
