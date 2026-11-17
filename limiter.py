import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared Rate Limiter instance across application routers
# In production, rate limits are fully enforced.
# During test runs (TESTING=1), rate limiting is disabled to allow large test suites to complete.
is_testing = bool(os.getenv("TESTING", ""))

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=not is_testing
)
