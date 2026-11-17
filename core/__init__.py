"""
Core module initialization.
"""
from core.rbac import (
    PlatformRole,
    normalize_role,
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin,
    is_candidate,
    has_permission,
    verify_org_access,
    enforce_org_access,
    Permission
)
from core.responses import success_response, error_response
