"""
modules/users/router.py
-----------------------
API v1 endpoints for User management.
"""
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import database, auth, models
from modules.users.schemas import UserCreateV1, UserUpdateV1, UserOutV1
from modules.users.service import UserService
from core.responses import success_response

router = APIRouter(tags=["API v1 - Users"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateV1,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    user = UserService.create_user(db, payload, current_user)
    return success_response(
        data=UserOutV1.model_validate(user).model_dump(),
        message="User created successfully",
        status_code=status.HTTP_201_CREATED
    )

@router.get("", status_code=status.HTTP_200_OK)
def list_users(
    organization_id: Optional[int] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    users = UserService.list_users(db, current_user, org_id=organization_id)
    return success_response(
        data=[UserOutV1.model_validate(u).model_dump() for u in users],
        message="Users retrieved successfully"
    )

@router.get("/{user_id}", status_code=status.HTTP_200_OK)
def get_user(
    user_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    user = UserService.get_user(db, user_id, current_user)
    return success_response(
        data=UserOutV1.model_validate(user).model_dump(),
        message="User retrieved successfully"
    )
