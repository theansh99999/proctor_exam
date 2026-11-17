"""
modules/admin/__init__.py
-------------------------
Phase 10 Platform Administration & System Configuration module.
"""
from modules.admin.router import router as admin_router
from modules.admin.service import AdminService

__all__ = ["admin_router", "AdminService"]
