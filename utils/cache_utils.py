import time
import threading
import json
import os
from typing import Any, Dict, Optional, Tuple

try:
    import redis
except ImportError:
    redis = None


class SimpleTTLCache:
    """
    Tiny in-process TTL cache suitable for caching computed JSON payloads.
    - Thread-safe within a single process
    - Not shared across Gunicorn workers
    - Evicts expired entries lazily and caps size
    """

    def __init__(self, maxsize: int = 1024):
        self._data: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < now:
                # Expired; remove and return miss
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = time.time() + max(0, int(ttl_seconds))
        with self._lock:
            # Simple cap: drop oldest arbitrary item if over size
            if len(self._data) >= self._maxsize:
                # Remove one item (not true LRU; good enough for small caches)
                try:
                    self._data.pop(next(iter(self._data)))
                except StopIteration:
                    pass
            self._data[key] = (expires_at, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class HybridCache:
    """
    Hybrid cache that prefers Redis (shared across workers) and falls back
    to in-process SimpleTTLCache if Redis is unavailable.
    """

    def __init__(self, prefix: str = "cache", maxsize: int = 1024):
        self._prefix = prefix
        self._fallback = SimpleTTLCache(maxsize=maxsize)
        self._redis_client = None
        self._redis_available = False
        self._init_redis()

    def _init_redis(self):
        """Try to initialize Redis connection"""
        if not redis:
            return
        try:
            redis_url = os.getenv("REDIS_URL")
            if not redis_url:
                return
            r = redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
            r.ping()
            self._redis_client = r
            self._redis_available = True
        except Exception:
            self._redis_available = False

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def get(self, key: str) -> Optional[Any]:
        # Try Redis first
        if self._redis_available and self._redis_client:
            try:
                cached = self._redis_client.get(self._key(key))
                if cached:
                    return json.loads(cached)
            except Exception:
                # Redis error, mark unavailable and fall through
                self._redis_available = False
        
        # Fallback to in-process cache
        return self._fallback.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        # Try Redis first
        if self._redis_available and self._redis_client:
            try:
                self._redis_client.setex(
                    self._key(key),
                    ttl_seconds,
                    json.dumps(value)
                )
                # Also store in fallback for quick local access
                self._fallback.set(key, value, ttl_seconds)
                return
            except Exception:
                # Redis error, mark unavailable and fall through
                self._redis_available = False
        
        # Fallback to in-process cache
        self._fallback.set(key, value, ttl_seconds)

    def clear(self) -> None:
        """Clear local cache only (Redis keys have TTL)"""
        self._fallback.clear()
