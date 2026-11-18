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
    get_dashboard_url,
    get_role_display_name,
    has_permission,
    verify_org_access,
    enforce_org_access,
    Permission
)
from core.responses import success_response, error_response
