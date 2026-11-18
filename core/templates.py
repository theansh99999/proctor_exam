"""
core/templates.py
-----------------
Centralized Jinja2 template engine configuration with global helper functions:
- get_dashboard_url: role-aware dashboard resolution
- get_role_display_name: clean UI role formatting
"""
from fastapi.templating import Jinja2Templates
from core.rbac import get_dashboard_url, get_role_display_name

templates = Jinja2Templates(directory="templates")
templates.env.globals["get_dashboard_url"] = get_dashboard_url
templates.env.globals["get_role_display_name"] = get_role_display_name
