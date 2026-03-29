"""Redis cache service for dashboard and calculation results."""
import json
import logging
from typing import Optional, Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            settings = get_settings()
            _redis_client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis not available: {e}. Cache disabled.")
            _redis_client = None
    return _redis_client


class CacheService:

    @staticmethod
    def get(key: str) -> Optional[Any]:
        r = _get_redis()
        if r is None:
            return None
        try:
            val = r.get(key)
            return json.loads(val) if val else None
        except Exception as e:
            logger.warning(f"Cache GET error for key '{key}': {e}")
            return None

    @staticmethod
    def set(key: str, value: Any, ttl: int = 300) -> bool:
        r = _get_redis()
        if r is None:
            return False
        try:
            r.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.warning(f"Cache SET error for key '{key}': {e}")
            return False

    @staticmethod
    def delete(key: str) -> bool:
        r = _get_redis()
        if r is None:
            return False
        try:
            r.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache DELETE error for key '{key}': {e}")
            return False

    @staticmethod
    def invalidate_pattern(pattern: str) -> int:
        r = _get_redis()
        if r is None:
            return 0
        try:
            keys = list(r.scan_iter(match=pattern))
            if keys:
                r.delete(*keys)
            return len(keys)
        except Exception as e:
            logger.warning(f"Cache INVALIDATE error for pattern '{pattern}': {e}")
            return 0
