"""
modules/integrations/__init__.py
--------------------------------
Package initializer for Phase 8 External Integrations.
"""
from modules.integrations.router import router as integration_router
from modules.integrations.service import IntegrationService
from modules.integrations.registry import get_provider, list_registered_providers
import modules.integrations.providers # Trigger registration of QuestionGenerator and ServiceNow
