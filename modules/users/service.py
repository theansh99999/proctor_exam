"""

modules/users/service.py

------------------------

Service logic for user management with role and organization scoping.

"""

from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from typing import List, Optional

import models, auth

from modules.users.schemas import UserCreateV1, UserUpdateV1

from core.rbac import (

    PlatformRole,

    normalize_role,

    is_super_admin,

    is_org_admin,

    enforce_org_access,

    ALL_PLATFORM_ROLES

)



class UserService:

    @staticmethod

    def create_user(db: Session, data: UserCreateV1, current_user: models.User) -> models.User:

        target_role = normalize_role(data.role)



        # Super admin can create any role in any org

        if is_super_admin(current_user):

            target_org_id = data.organization_id

        elif is_org_admin(current_user):

            # Org admin can only create examiner or candidate in their OWN org

            if target_role in (PlatformRole.SUPER_ADMIN, PlatformRole.ORG_ADMIN):

                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Org admins cannot create admin accounts.")

            target_org_id = current_user.organization_id

        else:

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to create users.")



        # Check duplicate email

        if db.query(models.User).filter(models.User.email == data.email).first():

            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")



        # Verify org exists if specified

        if target_org_id:

            org = db.query(models.Organization).filter(models.Organization.id == target_org_id).first()

            if not org:

                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target organization does not exist.")



        new_user = models.User(

            email=data.email,

            password_hash=auth.get_password_hash(data.password),

            name=data.name.strip(),

            role=data.role,

            organization_id=target_org_id

        )

        db.add(new_user)

        db.commit()

        db.refresh(new_user)

        return new_user



    @staticmethod

    def list_users(db: Session, current_user: models.User, org_id: Optional[int] = None) -> List[models.User]:

        if is_super_admin(current_user):

            query = db.query(models.User)

            if org_id is not None:

                query = query.filter(models.User.organization_id == org_id)

            return query.all()



        if is_org_admin(current_user):

            # Scoped strictly to org admin's own organization

            return db.query(models.User).filter(models.User.organization_id == current_user.organization_id).all()



        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to list users.")



    @staticmethod

    def get_user(db: Session, user_id: int, current_user: models.User) -> models.User:

        user = db.query(models.User).filter(models.User.id == user_id).first()

        if not user:

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")



        if is_super_admin(current_user):

            return user

        if is_org_admin(current_user):

            if user.organization_id != current_user.organization_id:

                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access users outside your organization.")

            return user

        if current_user.id == user_id:

            return user



        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this user.")
