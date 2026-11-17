"""
modules/users/schemas.py
------------------------
Pydantic schemas for User management API v1.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class UserCreateV1(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=1)
    role: str = Field("candidate", description="super_admin, org_admin, examiner, candidate")
    organization_id: Optional[int] = None

class UserUpdateV1(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    organization_id: Optional[int] = None

class UserOutV1(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: str
    organization_id: Optional[int] = None

    class Config:
        from_attributes = True
