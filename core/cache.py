"""
core/cache.py
-------------
Production-ready caching and state management:
- Redis connection pooling with automatic reconnection
- Thread-safe in-memory fallback cache when Redis is unavailable or offline
- TTL expiration support
- Pattern-based cache invalidation
- Safe non-blocking execution (failures degrade gracefully without breaking business requests)
- Cache health-check for readiness probes
"""
import time
import json
import logging
from typing import Optional, Any, Callable
from functools import wraps
import threading

logger = logging.getLogger("examproctor.cache")

# In-memory fallback cache
_local_cache: dict = {}
_local_cache_lock = threading.Lock()

_redis_client = None
_redis_available = False
_last_reconnect_attempt = 0.0


def _init_redis():
    global _redis_client, _redis_available, _last_reconnect_attempt
    _last_reconnect_attempt = time.time()
    from core.config import REDIS_URL, CACHE_ENABLED
    if not CACHE_ENABLED or not REDIS_URL:
        _redis_available = False
        return

    try:
        import redis
        pool = redis.ConnectionPool.from_url(
            REDIS_URL,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            max_connections=20
        )
        client = redis.Redis(connection_pool=pool)
        client.ping()
        _redis_client = client
        _redis_available = True
        logger.info("[CACHE] Successfully connected to Redis at %s", REDIS_URL.split("@")[-1])
    except Exception as e:
        _redis_available = False
        logger.warning("[CACHE] Redis unavailable (%s). Operating with in-memory TTL fallback cache.", str(e))


# Initialize on import
_init_redis()


def cache_get(key: str) -> Optional[Any]:
    """Retrieve value from Redis or in-memory fallback cache."""
    global _redis_available, _redis_client
    if _redis_available and _redis_client:
        try:
            val = _redis_client.get(key)
            if val is not None:
                return json.loads(val.decode("utf-8"))
            return None
        except Exception as e:
            logger.warning("[CACHE] Redis get error: %s. Falling back to local cache.", e)
            _redis_available = False

    # In-memory fallback
    with _local_cache_lock:
        entry = _local_cache.get(key)
        if entry:
            expires_at, data = entry
            if expires_at is None or expires_at > time.time():
                return data
            else:
                del _local_cache[key]
    return None


def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Store value in Redis or in-memory fallback cache with TTL."""
    global _redis_available, _redis_client
    serialized = json.dumps(value, default=str)

    if _redis_available and _redis_client:
        try:
            _redis_client.setex(key, ttl_seconds, serialized.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning("[CACHE] Redis set error: %s. Writing to local cache.", e)
            _redis_available = False

    # In-memory fallback
    expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
    with _local_cache_lock:
        _local_cache[key] = (expires_at, value)
    return True


def cache_delete(key: str) -> bool:
    """Delete a key from Redis and in-memory cache."""
    global _redis_available, _redis_client
    if _redis_available and _redis_client:
        try:
            _redis_client.delete(key)
        except Exception:
            pass

    with _local_cache_lock:
        _local_cache.pop(key, None)
    return True


def cache_delete_pattern(pattern: str) -> int:
    """Invalidate all keys matching a prefix or wildcard pattern (e.g. 'analytics:*')."""
    global _redis_available, _redis_client
    deleted = 0
    if _redis_available and _redis_client:
        try:
            keys = _redis_client.keys(pattern)
            if keys:
                deleted = _redis_client.delete(*keys)
        except Exception:
            pass

    import fnmatch
    with _local_cache_lock:
        keys_to_del = [k for k in _local_cache.keys() if fnmatch.fnmatch(k, pattern)]
        for k in keys_to_del:
            _local_cache.pop(k, None)
            deleted += 1
    return deleted


def check_redis_health() -> dict:
    """Check connectivity to Redis without leaking credentials."""
    global _redis_client, _redis_available, _last_reconnect_attempt
    # Throttled reconnection attempt: at most once every 15 seconds when offline
    if not _redis_available and (time.time() - _last_reconnect_attempt > 15.0):
        _init_redis()

    if _redis_available and _redis_client:
        try:
            _redis_client.ping()
            return {"status": "healthy", "redis": "connected", "mode": "distributed"}
        except Exception as e:
            return {"status": "degraded", "redis": "unreachable", "mode": "in_memory_fallback", "detail": str(e).split("\n")[0]}
    return {"status": "degraded", "redis": "not_configured", "mode": "in_memory_fallback"}
