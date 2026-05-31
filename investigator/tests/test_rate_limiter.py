import asyncio
import pytest
from investigator.lib.rate_limiter import RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert not await limiter.is_rate_limited("user1")
        assert not await limiter.is_rate_limited("user1")
        assert not await limiter.is_rate_limited("user1")

    @pytest.mark.asyncio
    async def test_blocks_exceeding_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert not await limiter.is_rate_limited("user1")
        assert not await limiter.is_rate_limited("user1")
        assert await limiter.is_rate_limited("user1")

    @pytest.mark.asyncio
    async def test_returns_remaining(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert await limiter.remaining("user1") == 5
        await limiter.is_rate_limited("user1")
        assert await limiter.remaining("user1") == 4

    @pytest.mark.asyncio
    async def test_expires_after_window(self):
        limiter = RateLimiter(max_requests=1, window_seconds=0.1)
        assert not await limiter.is_rate_limited("user1")
        assert await limiter.is_rate_limited("user1")
        await asyncio.sleep(0.15)
        assert not await limiter.is_rate_limited("user1")

    @pytest.mark.asyncio
    async def test_separate_buckets_per_user(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert not await limiter.is_rate_limited("alice")
        assert await limiter.is_rate_limited("alice")
        assert not await limiter.is_rate_limited("bob")

    @pytest.mark.asyncio
    async def test_reset_single_user(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        await limiter.is_rate_limited("user1")
        assert await limiter.is_rate_limited("user1")
        await limiter.reset("user1")
        assert not await limiter.is_rate_limited("user1")

    @pytest.mark.asyncio
    async def test_reset_all(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        await limiter.is_rate_limited("user1")
        await limiter.is_rate_limited("user2")
        await limiter.reset()
        assert not await limiter.is_rate_limited("user1")
        assert not await limiter.is_rate_limited("user2")

    @pytest.mark.asyncio
    async def test_custom_max_and_window(self):
        limiter = RateLimiter(max_requests=10, window_seconds=5)
        for _ in range(10):
            assert not await limiter.is_rate_limited("user1")
        assert await limiter.is_rate_limited("user1")
