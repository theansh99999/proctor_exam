"""
modules/organizations/router.py
-------------------------------
API v1 endpoints for Organization management.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
import database, auth, models
from modules.organizations.schemas import OrganizationCreate, OrganizationUpdate, OrganizationOut
from modules.organizations.service import OrganizationService
from core.responses import success_response

router = APIRouter(tags=["API v1 - Organizations"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_org(
    payload: OrganizationCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    org = OrganizationService.create_organization(db, payload, current_user)
    return success_response(
        data=OrganizationOut.model_validate(org).model_dump(),
        message="Organization created successfully",
        status_code=status.HTTP_201_CREATED
    )

@router.get("", status_code=status.HTTP_200_OK)
def list_orgs(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    orgs = OrganizationService.list_organizations(db, current_user)
    return success_response(
        data=[OrganizationOut.model_validate(o).model_dump() for o in orgs],
        message="Organizations retrieved successfully"
    )

@router.get("/{org_id}", status_code=status.HTTP_200_OK)
def get_org(
    org_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    org = OrganizationService.get_organization(db, org_id, current_user)
    return success_response(
        data=OrganizationOut.model_validate(org).model_dump(),
        message="Organization details retrieved"
    )

@router.put("/{org_id}", status_code=status.HTTP_200_OK)
def update_org(
    org_id: int,
    payload: OrganizationUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    org = OrganizationService.update_organization(db, org_id, payload, current_user)
    return success_response(
        data=OrganizationOut.model_validate(org).model_dump(),
        message="Organization updated successfully"
    )
