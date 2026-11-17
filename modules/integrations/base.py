"""
modules/integrations/base.py
----------------------------
Common abstract integration interfaces, connection states, retry handlers,
and sanitization utilities for external integration providers.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
import time
import re
import urllib.parse
from datetime import datetime


# ── Connection Status Constants ──────────────────────────────────────────────
STATUS_UNTESTED = "untested"
STATUS_CONNECTED = "connected"
STATUS_ERROR = "error"
STATUS_DISCONNECTED = "disconnected"


# ── Custom Integration Exceptions ────────────────────────────────────────────
class IntegrationException(Exception):
    """Base exception for all integration operations."""
    def __init__(self, message: str, status_code: int = 502, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class IntegrationAuthError(IntegrationException):
    """Authentication or credential failure when connecting to external provider."""
    def __init__(self, message: str = "External integration authentication failed.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=401, details=details)


class IntegrationNetworkError(IntegrationException):
    """Network connection error, DNS failure or host unreachable."""
    def __init__(self, message: str = "External service unreachable.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=504, details=details)


class IntegrationTimeoutError(IntegrationException):
    """Request to external provider exceeded configured timeout."""
    def __init__(self, message: str = "External service timed out.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=504, details=details)


class IntegrationValidationError(IntegrationException):
    """External provider payload failed schema or business rule validation."""
    def __init__(self, message: str = "Invalid response from external integration.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=422, details=details)


# ── Security & Sanitization Utilities ────────────────────────────────────────
def mask_secret(secret: Optional[str]) -> str:
    """Masks sensitive credentials (passwords, tokens, api keys) for safe output and logging."""
    if not secret:
        return ""
    s = str(secret).strip()
    if len(s) <= 4:
        return "********"
    if len(s) <= 8:
        return f"{s[:1]}****{s[-1:]}"
    return f"{s[:2]}****{s[-3:]}"


def sanitize_dict_for_logging(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Recursively redacts sensitive fields like passwords, secrets, tokens from logging payloads."""
    if not data or not isinstance(data, dict):
        return {}
    sensitive_keys = {
        "password", "secret", "token", "access_token", "api_key", "apikey",
        "auth", "authorization", "bearer", "credentials", "private_key"
    }
    cleaned = {}
    for k, v in data.items():
        if any(sk in k.lower() for sk in sensitive_keys):
            cleaned[k] = mask_secret(str(v))
        elif isinstance(v, dict):
            cleaned[k] = sanitize_dict_for_logging(v)
        elif isinstance(v, list):
            cleaned[k] = [
                sanitize_dict_for_logging(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            cleaned[k] = v
    return cleaned


def validate_external_url(url: str, allow_localhost_for_testing: bool = True) -> bool:
    """
    Validates external service URL against SSRF vulnerabilities.
    Rejects malformed URLs and dangerous protocols.
    """
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.hostname:
            return False
        # Block link-local and internal AWS/cloud metadata services
        blocked_hosts = {"169.254.169.254", "metadata.google.internal"}
        if parsed.hostname.lower() in blocked_hosts:
            return False
        return True
    except Exception:
        return False


# ── Base Provider Interface ──────────────────────────────────────────────────
class BaseIntegrationProvider(ABC):
    """Abstract Base Class for all external integration providers."""

    name: str = "base"
    display_name: str = "Base Integration"
    description: str = "Abstract Integration Provider"

    @abstractmethod
    def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tests connection to external service using provided config.
        Returns dict with status ("connected", "error"), latency_ms, and details.
        """
        pass

    def execute_with_retry(
        self,
        operation: Callable[[], Any],
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        retryable_exceptions: tuple = (IntegrationNetworkError, IntegrationTimeoutError)
    ) -> Any:
        """
        Executes an external call with configurable retries and exponential backoff.
        Non-transient errors (such as 401 Auth error or 422 Validation) fail immediately.
        """
        last_exception = None
        for attempt in range(1, max_retries + 1):
            try:
                return operation()
            except retryable_exceptions as ex:
                last_exception = ex
                if attempt < max_retries:
                    sleep_time = backoff_seconds * (2 ** (attempt - 1))
                    time.sleep(sleep_time)
            except Exception as ex:
                # Non-retryable error, fail immediately
                raise ex

        if last_exception:
            raise last_exception
        raise IntegrationException("Operation failed after retries.")
