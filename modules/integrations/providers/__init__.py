"""
modules/integrations/providers/__init__.py
------------------------------------------
Registers built-in integration providers into the central registry.
"""
from modules.integrations.registry import register_provider
from modules.integrations.providers.question_generator import QuestionGeneratorProvider
from modules.integrations.providers.servicenow import ServiceNowProvider

# Register standard providers
register_provider("question_generator", QuestionGeneratorProvider)
register_provider("servicenow", ServiceNowProvider)
