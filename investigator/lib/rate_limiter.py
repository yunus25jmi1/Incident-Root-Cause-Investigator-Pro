import logging
import time
from collections import defaultdict, deque
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self._max_requests = max_requests
        self._window = window_seconds
        self._buckets: dict[str, deque] = defaultdict(deque)

    def is_rate_limited(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._buckets[key]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max_requests:
            return True
        bucket.append(now)
        return False

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        bucket = self._buckets[key]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return max(0, self._max_requests - len(bucket))

    def reset(self, key: Optional[str] = None) -> None:
        if key:
            self._buckets.pop(key, None)
        else:
            self._buckets.clear()
