"""

core/rbac.py

------------

Centralized Role-Based Access Control (RBAC) and Organization-level isolation foundation.

Supports platform roles:

- super_admin: Platform-wide access

- org_admin: Organization-scoped admin

- examiner: Creates and manages assessments, groups, candidates within org/scope (legacy: teacher)

- candidate: Takes assessments, views own attempts and results (legacy: student)

"""

from typing import Set, Optional, Dict, Any, List

from fastapi import HTTPException, status, Request, Depends

from sqlalchemy.orm import Session

import database



# ── Canonical Role Constants ──────────────────────────────────────────────────

class PlatformRole:

    SUPER_ADMIN = "super_admin"

    ORG_ADMIN = "org_admin"

    EXAMINER = "examiner"

    CANDIDATE = "candidate"



    # Legacy aliases (100% backward compatible)

    TEACHER = "teacher"

    STUDENT = "student"



# Mapping sets

TEACHER_ROLES: Set[str] = {PlatformRole.TEACHER, PlatformRole.EXAMINER}

STUDENT_ROLES: Set[str] = {PlatformRole.STUDENT, PlatformRole.CANDIDATE}

ADMIN_ROLES: Set[str] = {PlatformRole.SUPER_ADMIN, PlatformRole.ORG_ADMIN}

ALL_PLATFORM_ROLES: Set[str] = {

    PlatformRole.SUPER_ADMIN,

    PlatformRole.ORG_ADMIN,

    PlatformRole.EXAMINER,

    PlatformRole.CANDIDATE,

    PlatformRole.TEACHER,

    PlatformRole.STUDENT

}



def normalize_role(role: Optional[str]) -> str:

    """Normalize legacy role names to canonical platform roles."""

    if not role:

        return PlatformRole.CANDIDATE

    r = role.strip().lower()

    if r in (PlatformRole.TEACHER, PlatformRole.EXAMINER):

        return PlatformRole.EXAMINER

    if r in (PlatformRole.STUDENT, PlatformRole.CANDIDATE):

        return PlatformRole.CANDIDATE

    if r in (PlatformRole.ORG_ADMIN, "admin"):

        return PlatformRole.ORG_ADMIN

    if r == PlatformRole.SUPER_ADMIN:

        return PlatformRole.SUPER_ADMIN

    return r



def is_super_admin(user: Any) -> bool:

    """Check if user has super admin privileges."""

    return getattr(user, "role", None) == PlatformRole.SUPER_ADMIN



def is_org_admin(user: Any) -> bool:

    """Check if user is an organization admin or super admin."""

    norm = normalize_role(getattr(user, "role", None))

    return norm in (PlatformRole.ORG_ADMIN, PlatformRole.SUPER_ADMIN)



def is_examiner_or_admin(user: Any) -> bool:

    """Check if user has examiner/teacher or administrative rights."""

    norm = normalize_role(getattr(user, "role", None))

    return norm in (PlatformRole.EXAMINER, PlatformRole.ORG_ADMIN, PlatformRole.SUPER_ADMIN)



def is_candidate(user: Any) -> bool:

    """Check if user is a student or candidate."""

    norm = normalize_role(getattr(user, "role", None))

    return norm == PlatformRole.CANDIDATE



# ── Permissions Definition ─────────────────────────────────────────────────────

class Permission:

    # Organization

    ORG_CREATE = "org:create"

    ORG_READ = "org:read"

    ORG_UPDATE = "org:update"

    ORG_DELETE = "org:delete"



    # Users

    USER_CREATE = "user:create"

    USER_READ = "user:read"

    USER_UPDATE = "user:update"

    USER_DELETE = "user:delete"



    # Assessments

    ASSESSMENT_CREATE = "assessment:create"

    ASSESSMENT_READ = "assessment:read"

    ASSESSMENT_UPDATE = "assessment:update"

    ASSESSMENT_DELETE = "assessment:delete"

    ASSESSMENT_PUBLISH = "assessment:publish"



    # Attempts & Results

    ATTEMPT_START = "attempt:start"

    ATTEMPT_SUBMIT = "attempt:submit"

    RESULT_READ_OWN = "result:read_own"

    RESULT_READ_ALL = "result:read_all"



# Default role permissions map

ROLE_PERMISSIONS: Dict[str, Set[str]] = {

    PlatformRole.SUPER_ADMIN: {

        Permission.ORG_CREATE, Permission.ORG_READ, Permission.ORG_UPDATE, Permission.ORG_DELETE,

        Permission.USER_CREATE, Permission.USER_READ, Permission.USER_UPDATE, Permission.USER_DELETE,

        Permission.ASSESSMENT_CREATE, Permission.ASSESSMENT_READ, Permission.ASSESSMENT_UPDATE,

        Permission.ASSESSMENT_DELETE, Permission.ASSESSMENT_PUBLISH,

        Permission.ATTEMPT_START, Permission.ATTEMPT_SUBMIT,

        Permission.RESULT_READ_OWN, Permission.RESULT_READ_ALL

    },

    PlatformRole.ORG_ADMIN: {

        Permission.ORG_READ, Permission.ORG_UPDATE,

        Permission.USER_CREATE, Permission.USER_READ, Permission.USER_UPDATE,

        Permission.ASSESSMENT_CREATE, Permission.ASSESSMENT_READ, Permission.ASSESSMENT_UPDATE,

        Permission.ASSESSMENT_DELETE, Permission.ASSESSMENT_PUBLISH,

        Permission.RESULT_READ_ALL

    },

    PlatformRole.EXAMINER: {

        Permission.ORG_READ,

        Permission.ASSESSMENT_CREATE, Permission.ASSESSMENT_READ, Permission.ASSESSMENT_UPDATE,

        Permission.ASSESSMENT_DELETE, Permission.ASSESSMENT_PUBLISH,

        Permission.RESULT_READ_ALL

    },

    PlatformRole.CANDIDATE: {

        Permission.ASSESSMENT_READ,

        Permission.ATTEMPT_START, Permission.ATTEMPT_SUBMIT,

        Permission.RESULT_READ_OWN

    }

}



def has_permission(user: Any, permission: str) -> bool:

    """Check if user's role grants the requested permission."""

    if not user:

        return False

    norm_role = normalize_role(getattr(user, "role", None))

    perms = ROLE_PERMISSIONS.get(norm_role, set())

    return permission in perms



# ── Organization-Level Isolation Checks ─────────────────────────────────────────

def verify_org_access(user: Any, resource_org_id: Optional[int], allow_legacy_unaffiliated: bool = True) -> bool:

    """

    Backend organization-level access verification.

    Rules:

    1. Super Admin has unrestricted platform-wide access across all organizations.

    2. Legacy Unaffiliated User (organization_id is None):

       - If resource_org_id is None: Allowed (preserves 100% legacy behavior without forcing fake orgs).

       - If resource_org_id is set: Denied unless user is Super Admin.

    3. User belongs to an Organization (user.organization_id is not None):

       - Can only access resources where resource.organization_id == user.organization_id.

       - If resource_org_id is None: Allowed for legacy global read/unaffiliated if enabled, otherwise denied.

       - If resource_org_id != user.organization_id: STRICTLY DENIED.

    """

    if not user:

        return False

    if is_super_admin(user):

        return True



    user_org_id = getattr(user, "organization_id", None)



    if user_org_id is None:

        # Legacy unaffiliated user

        if resource_org_id is None and allow_legacy_unaffiliated:

            return True

        return False



    # Org-bound user

    if resource_org_id is None:

        return allow_legacy_unaffiliated



    return user_org_id == resource_org_id



def enforce_org_access(user: Any, resource_org_id: Optional[int], resource_name: str = "resource") -> None:

    """Raise HTTP 403 Forbidden if user is not authorized to access the given organization resource."""

    if not verify_org_access(user, resource_org_id):

        raise HTTPException(

            status_code=status.HTTP_403_FORBIDDEN,

            detail=f"Access denied: you do not have permission to access this {resource_name} across organization boundaries."

        )
