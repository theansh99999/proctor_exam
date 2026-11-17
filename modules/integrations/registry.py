"""
modules/integrations/registry.py
--------------------------------
Central registry for discovering, registering, and instantiating external
integration providers dynamically.
"""
from typing import Dict, Type, List, Any, Optional
from modules.integrations.base import BaseIntegrationProvider

_PROVIDER_REGISTRY: Dict[str, Type[BaseIntegrationProvider]] = {}


def register_provider(name: str, provider_cls: Type[BaseIntegrationProvider]):
    """Registers an integration provider class by its unique key."""
    _PROVIDER_REGISTRY[name.lower()] = provider_cls


def get_provider_class(name: str) -> Optional[Type[BaseIntegrationProvider]]:
    """Retrieves a provider class by name."""
    return _PROVIDER_REGISTRY.get(name.lower())


def get_provider(name: str) -> BaseIntegrationProvider:
    """Instantiates and returns an integration provider."""
    cls = get_provider_class(name)
    if not cls:
        raise KeyError(f"Integration provider '{name}' is not registered.")
    return cls()


def list_registered_providers() -> List[Dict[str, Any]]:
    """Lists metadata for all registered providers."""
    result = []
    for key, cls in _PROVIDER_REGISTRY.items():
        result.append({
            "name": getattr(cls, "name", key),
            "display_name": getattr(cls, "display_name", key.capitalize()),
            "description": getattr(cls, "description", "")
        })
    return result
