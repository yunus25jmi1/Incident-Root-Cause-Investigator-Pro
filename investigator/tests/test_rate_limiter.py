import time
import pytest
from investigator.lib.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert not limiter.is_rate_limited("user1")
        assert not limiter.is_rate_limited("user1")
        assert not limiter.is_rate_limited("user1")

    def test_blocks_exceeding_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert not limiter.is_rate_limited("user1")
        assert not limiter.is_rate_limited("user1")
        assert limiter.is_rate_limited("user1")

    def test_returns_remaining(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert limiter.remaining("user1") == 5
        limiter.is_rate_limited("user1")
        assert limiter.remaining("user1") == 4

    def test_expires_after_window(self):
        limiter = RateLimiter(max_requests=1, window_seconds=0.1)
        assert not limiter.is_rate_limited("user1")
        assert limiter.is_rate_limited("user1")
        time.sleep(0.15)
        assert not limiter.is_rate_limited("user1")

    def test_separate_buckets_per_user(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert not limiter.is_rate_limited("alice")
        assert limiter.is_rate_limited("alice")
        assert not limiter.is_rate_limited("bob")

    def test_reset_single_user(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        limiter.is_rate_limited("user1")
        assert limiter.is_rate_limited("user1")
        limiter.reset("user1")
        assert not limiter.is_rate_limited("user1")

    def test_reset_all(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        limiter.is_rate_limited("user1")
        limiter.is_rate_limited("user2")
        limiter.reset()
        assert not limiter.is_rate_limited("user1")
        assert not limiter.is_rate_limited("user2")

    def test_custom_max_and_window(self):
        limiter = RateLimiter(max_requests=10, window_seconds=5)
        for _ in range(10):
            assert not limiter.is_rate_limited("user1")
        assert limiter.is_rate_limited("user1")
