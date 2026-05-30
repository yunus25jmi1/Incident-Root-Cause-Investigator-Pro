import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REDIS_URL: str = os.environ.get("REDIS_URL", "").strip()
_USE_REDIS: bool = bool(_REDIS_URL)

_redis_client: Any = None


def _get_redis():
    global _redis_client
    if _redis_client is None and _USE_REDIS:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
            logger.info("Connected to Redis at %s", _REDIS_URL)
        except Exception as e:
            logger.warning("Redis connection failed (%s) — falling back to file-based", e)
    return _redis_client


class RedisQueuePersistence:
    def __init__(self, redis_key: str = "investigator:queue"):
        self._redis_key = redis_key
        self._r = _get_redis()

    def is_available(self) -> bool:
        return self._r is not None

    async def save(self, item: tuple) -> None:
        if not self._r:
            return
        question, channel, thread_ts, since, service = item
        entry = {
            "question": question,
            "channel": channel,
            "thread_ts": thread_ts,
            "since": since,
            "service": service,
            "created_at": time.time(),
            "status": "pending",
        }
        try:
            await self._r.rpush(self._redis_key, json.dumps(entry))
        except Exception as e:
            logger.warning("Redis save failed: %s", e)

    async def remove(self, item: tuple) -> None:
        if not self._r:
            return
        question, channel, thread_ts, _, _ = item
        try:
            entries = await self._r.lrange(self._redis_key, 0, -1)
            for entry_json in entries:
                try:
                    entry = json.loads(entry_json)
                    if (entry.get("question") == question
                            and entry.get("channel") == channel
                            and entry.get("thread_ts") == thread_ts):
                        await self._r.lrem(self._redis_key, 1, entry_json)
                        break
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.warning("Redis remove failed: %s", e)

    async def load(self) -> list[dict[str, Any]]:
        if not self._r:
            return []
        try:
            entries = await self._r.lrange(self._redis_key, 0, -1)
            result = []
            for entry_json in entries:
                try:
                    result.append(json.loads(entry_json))
                except json.JSONDecodeError:
                    continue
            return result
        except Exception as e:
            logger.warning("Redis load failed: %s", e)
            return []

    async def clear(self) -> None:
        if not self._r:
            return
        try:
            await self._r.delete(self._redis_key)
        except Exception as e:
            logger.warning("Redis clear failed: %s", e)


class RedisRateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self._max_requests = max_requests
        self._window = window_seconds
        self._r = _get_redis()
        self._in_memory: dict[str, deque] = defaultdict(deque)

    async def is_rate_limited(self, key: str) -> bool:
        if self._r:
            return await self._redis_is_limited(key)
        return self._mem_is_limited(key)

    async def remaining(self, key: str) -> int:
        if self._r:
            return await self._redis_remaining(key)
        return self._mem_remaining(key)

    async def reset(self, key: Optional[str] = None) -> None:
        if self._r:
            if key:
                await self._r.delete(f"investigator:ratelimit:{key}")
        elif key:
            self._in_memory.pop(key, None)
        else:
            self._in_memory.clear()

    async def _redis_is_limited(self, key: str) -> bool:
        rk = f"investigator:ratelimit:{key}"
        now = int(time.time())
        window_start = now - int(self._window)
        try:
            await self._r.zremrangebyscore(rk, 0, window_start)
            count = await self._r.zcard(rk)
            if count >= self._max_requests:
                return True
            await self._r.zadd(rk, {str(now): now})
            await self._r.expire(rk, int(self._window) * 2)
            return False
        except Exception as e:
            logger.warning("Redis rate limit check failed: %s — falling back to in-memory", e)
            return self._mem_is_limited(key)

    async def _redis_remaining(self, key: str) -> int:
        rk = f"investigator:ratelimit:{key}"
        now = int(time.time())
        window_start = now - int(self._window)
        try:
            await self._r.zremrangebyscore(rk, 0, window_start)
            count = await self._r.zcard(rk)
            return max(0, self._max_requests - count)
        except Exception:
            return self._max_requests

    def _mem_is_limited(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._in_memory[key]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max_requests:
            return True
        bucket.append(now)
        return False

    def _mem_remaining(self, key: str) -> int:
        now = time.monotonic()
        bucket = self._in_memory[key]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return max(0, self._max_requests - len(bucket))
