"""
modules/admin/schemas.py
------------------------
Pydantic schemas for Phase 10 Platform Administration & System Configuration.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# =============================================================================
# Organization Schemas
# =============================================================================

class OrganizationCreateAdmin(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    slug: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    is_active: bool = True
    is_suspended: bool = False
    admin_user_id: Optional[int] = None

class OrganizationUpdateAdmin(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_suspended: Optional[bool] = None

class OrganizationStatusUpdate(BaseModel):
    action: str = Field(..., description="activate, deactivate, suspend, reactivate")
    reason: Optional[str] = None

class AssignAdminRequest(BaseModel):
    user_id: int

class OrganizationOutAdmin(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    is_active: bool
    is_suspended: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    total_users: Optional[int] = 0
    total_exams: Optional[int] = 0

    class Config:
        from_attributes = True

# =============================================================================
# User Administration Schemas
# =============================================================================

class UserCreateAdmin(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=8)
    role: str = Field("candidate", description="super_admin, org_admin, examiner, candidate")
    organization_id: Optional[int] = None
    is_active: bool = True
    is_suspended: bool = False

class UserUpdateAdmin(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    organization_id: Optional[int] = None

class UserRoleUpdate(BaseModel):
    role: str = Field(..., description="Target role: super_admin, org_admin, examiner, candidate")

class UserStatusUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_suspended: Optional[bool] = None
    reason: Optional[str] = None

class UserPasswordReset(BaseModel):
    new_password: Optional[str] = Field(None, min_length=8)

class UserOutAdmin(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: str
    organization_id: Optional[int] = None
    organization_name: Optional[str] = None
    is_active: bool = True
    is_suspended: bool = False

    class Config:
        from_attributes = True

# =============================================================================
# Configuration Schemas
# =============================================================================

class PlatformConfigItem(BaseModel):
    key: str
    value: Any
    value_type: str = "string"
    description: Optional[str] = None
    is_sensitive: bool = False

class PlatformConfigUpdateBatch(BaseModel):
    configs: Dict[str, Any]

class OrgConfigItem(BaseModel):
    key: str
    value: Any
    value_type: str = "string"

class OrgConfigUpdateBatch(BaseModel):
    configs: Dict[str, Any]

# =============================================================================
# Audit Log Schemas
# =============================================================================

class AuditLogOut(BaseModel):
    id: int
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    organization_id: Optional[int] = None
    organization_name: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    ip_address: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# =============================================================================
# Dashboard & Activity Schemas
# =============================================================================

class SuperAdminDashboardOut(BaseModel):
    total_organizations: int
    active_organizations: int
    inactive_organizations: int
    suspended_organizations: int
    total_users: int
    total_org_admins: int
    total_examiners: int
    total_candidates: int
    suspended_users: int
    total_assessments: int
    active_assessments: int
    completed_assessments: int
    total_attempts: int
    recent_organizations: List[Dict[str, Any]]
    recent_audit_actions: List[Dict[str, Any]]
    integration_health: Dict[str, Any]
    notification_health: Dict[str, Any]

class ActivityMonitoringOut(BaseModel):
    recent_activity: List[Dict[str, Any]]
    failed_logins_summary: Dict[str, Any]
    suspended_users_summary: Dict[str, Any]
    integration_failures_summary: Dict[str, Any]
    notification_failures_summary: Dict[str, Any]

class BulkImportResult(BaseModel):
    total_processed: int
    successful_imports: int
    failed_imports: int
    errors: List[Dict[str, Any]]
