"""

modules/organizations/service.py

--------------------------------

Service logic for organization management and isolation enforcement.

"""

from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from typing import List, Optional

import models

from modules.organizations.schemas import OrganizationCreate, OrganizationUpdate

from core.rbac import is_super_admin, is_org_admin, enforce_org_access



class OrganizationService:

    @staticmethod

    def create_organization(db: Session, data: OrganizationCreate, current_user: models.User) -> models.Organization:

        if not is_super_admin(current_user):

            raise HTTPException(

                status_code=status.HTTP_403_FORBIDDEN,

                detail="Only platform Super Admins can create new organizations."

            )



        # Check uniqueness of name and slug

        if db.query(models.Organization).filter(models.Organization.name == data.name).first():

            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization name already exists.")

        if db.query(models.Organization).filter(models.Organization.slug == data.slug).first():

            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization slug already exists.")



        org = models.Organization(

            name=data.name.strip(),

            slug=data.slug.strip().lower(),

            description=data.description,

            is_active=data.is_active

        )

        db.add(org)

        db.commit()

        db.refresh(org)

        return org



    @staticmethod

    def get_organization(db: Session, org_id: int, current_user: models.User) -> models.Organization:

        org = db.query(models.Organization).filter(models.Organization.id == org_id).first()

        if not org:

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")



        # Isolation check: super_admin or org member/admin

        enforce_org_access(current_user, org.id, resource_name="organization")

        return org



    @staticmethod

    def list_organizations(db: Session, current_user: models.User) -> List[models.Organization]:

        if is_super_admin(current_user):

            return db.query(models.Organization).all()



        # Org Admins and members only see their own organization

        if current_user.organization_id is not None:

            org = db.query(models.Organization).filter(models.Organization.id == current_user.organization_id).first()

            return [org] if org else []



        # Legacy unaffiliated users have no organizations

        return []



    @staticmethod

    def update_organization(db: Session, org_id: int, data: OrganizationUpdate, current_user: models.User) -> models.Organization:

        org = OrganizationService.get_organization(db, org_id, current_user)



        # Check permissions: super admin or org admin of this org

        if not (is_super_admin(current_user) or (is_org_admin(current_user) and current_user.organization_id == org_id)):

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this organization.")



        if data.name is not None:

            existing = db.query(models.Organization).filter(models.Organization.name == data.name, models.Organization.id != org_id).first()

            if existing:

                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization name already taken.")

            org.name = data.name.strip()



        if data.description is not None:

            org.description = data.description



        if data.is_active is not None:

            if not is_super_admin(current_user):

                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Super Admins can alter organization active status.")

            org.is_active = data.is_active



        db.commit()

        db.refresh(org)

        return org
