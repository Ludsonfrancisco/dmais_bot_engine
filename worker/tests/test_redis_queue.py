import pytest
import fakeredis.aioredis

from worker.redis_queue import RedisQueue


@pytest.fixture
def rq():
    q = RedisQueue()
    q._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return q


async def test_is_duplicate_event_first_call_returns_false(rq):
    assert await rq.is_duplicate_event("evt-001") is False


async def test_is_duplicate_event_second_call_returns_true(rq):
    await rq.is_duplicate_event("evt-002")
    assert await rq.is_duplicate_event("evt-002") is True


async def test_was_sent_false_before_mark(rq):
    assert await rq.was_sent(999) is False


async def test_mark_sent_then_was_sent_true(rq):
    await rq.mark_sent(42)
    assert await rq.was_sent(42) is True


async def test_incr_error_increments_consecutively(rq):
    assert await rq.incr_error("chat-1") == 1
    assert await rq.incr_error("chat-1") == 2
    assert await rq.incr_error("chat-1") == 3


async def test_reset_error_clears_counter(rq):
    await rq.incr_error("chat-2")
    await rq.incr_error("chat-2")
    await rq.reset_error("chat-2")
    assert await rq.incr_error("chat-2") == 1


async def test_track_activity_sets_sorted_set_entry(rq):
    await rq.track_activity("5511999998888")
    score = await rq._ensure_client().zscore("timeout_watch", "5511999998888")
    assert score is not None


async def test_clear_activity_removes_sorted_set_entry(rq):
    await rq.track_activity("5511999998888")
    await rq.clear_activity("5511999998888")
    assert await rq._ensure_client().zscore("timeout_watch", "5511999998888") is None


async def test_scan_timeouts_returns_expired(rq):
    import time
    client = rq._ensure_client()
    await client.zadd("timeout_watch", {"phone1": time.time() - 100})
    await client.zadd("timeout_watch", {"phone2": time.time() + 10000})
    result = await rq.scan_timeouts()
    assert "phone1" in result
    assert "phone2" not in result
