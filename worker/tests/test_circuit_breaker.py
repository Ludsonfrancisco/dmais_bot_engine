"""Tests for the Redis-backed circuit breaker.

Uses ``fakeredis.aioredis`` (the project's standard test pattern) so the breaker runs
against real Redis semantics — per-endpoint keys, pipelines, TTLs and all.
"""

import asyncio

import fakeredis.aioredis
import pytest
from unittest.mock import AsyncMock, patch

from worker.circuit_breaker import CircuitBreaker, CircuitState, _SOFT_WARNING_THRESHOLD
from worker.redis_queue import redis_queue


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_redis():
    """Point the shared redis_queue singleton at an isolated FakeRedis."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_queue._client = fake
    yield fake
    redis_queue._client = None


def _make_breaker(**kwargs) -> CircuitBreaker:
    """Create a breaker with low thresholds for fast tests."""
    return CircuitBreaker(
        failure_threshold=kwargs.get("failure_threshold", 3),
        recovery_timeout=kwargs.get("recovery_timeout", 1.0),
        max_recovery_timeout=kwargs.get("max_recovery_timeout", 7200),
    )


async def _fail(breaker: CircuitBreaker, times: int, endpoint: str = "default") -> None:
    for _ in range(times):
        await breaker.record_failure(endpoint)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initial_state_is_closed():
    """A fresh breaker should start in CLOSED state."""
    breaker = _make_breaker()
    assert await breaker.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_before_call_allowed_when_closed():
    """When CLOSED, before_call should return True."""
    breaker = _make_breaker()
    assert await breaker.before_call() is True


@pytest.mark.asyncio
async def test_opens_after_threshold_failures():
    """After N consecutive failures, the breaker should transition to OPEN."""
    breaker = _make_breaker(failure_threshold=3)
    await _fail(breaker, 3)
    assert await breaker.get_state() == CircuitState.OPEN


@pytest.mark.asyncio
async def test_before_call_blocked_when_open():
    """When OPEN and within recovery window, before_call returns False."""
    breaker = _make_breaker(failure_threshold=3, recovery_timeout=900)
    await _fail(breaker, 3)
    assert await breaker.before_call() is False


@pytest.mark.asyncio
async def test_transitions_to_half_open_after_recovery_timeout():
    """After recovery_timeout elapses, OPEN -> HALF_OPEN and before_call returns True."""
    breaker = _make_breaker(failure_threshold=3, recovery_timeout=0.05)
    await _fail(breaker, 3)
    assert await breaker.before_call() is False  # still within window

    await asyncio.sleep(0.06)
    assert await breaker.before_call() is True
    assert await breaker.get_state() == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_success_closes_circuit():
    """A success should reset the breaker to CLOSED."""
    breaker = _make_breaker(failure_threshold=3)
    await _fail(breaker, 3)
    assert await breaker.get_state() == CircuitState.OPEN

    await breaker.record_success_async()
    assert await breaker.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_failure_in_half_open_re_opens():
    """A failure in HALF_OPEN should immediately re-open the circuit."""
    breaker = _make_breaker(failure_threshold=3, recovery_timeout=0.05)
    await _fail(breaker, 3)

    await asyncio.sleep(0.06)
    assert await breaker.before_call() is True  # -> HALF_OPEN
    assert await breaker.get_state() == CircuitState.HALF_OPEN

    await breaker.record_failure()
    assert await breaker.get_state() == CircuitState.OPEN


@pytest.mark.asyncio
async def test_is_open_returns_false_when_closed():
    """is_open() should return False when circuit is CLOSED."""
    breaker = _make_breaker()
    assert await breaker.is_open() is False


@pytest.mark.asyncio
async def test_is_open_returns_true_when_open_within_window():
    """is_open() should return True when circuit is OPEN and within recovery window."""
    breaker = _make_breaker(failure_threshold=3, recovery_timeout=900)
    await _fail(breaker, 3)
    assert await breaker.is_open() is True


@pytest.mark.asyncio
async def test_reset_forces_closed(fake_redis):
    """reset() should force the breaker to CLOSED and clear failure count."""
    breaker = _make_breaker(failure_threshold=3)
    await _fail(breaker, 3)
    assert await breaker.get_state() == CircuitState.OPEN

    await breaker.reset()
    assert await breaker.get_state() == CircuitState.CLOSED
    assert await fake_redis.get("circuit:evolution:default:failures") == "0"
    assert await fake_redis.get("circuit:evolution:default:open_count") is None


# ---------------------------------------------------------------------------
# Per-endpoint tracking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_per_endpoint_isolation():
    """Failures on one endpoint must not open the circuit for another."""
    breaker = _make_breaker(failure_threshold=3)
    await _fail(breaker, 3, endpoint="sendText")

    assert await breaker.get_state("sendText") == CircuitState.OPEN
    assert await breaker.get_state("sendList") == CircuitState.CLOSED
    assert await breaker.before_call("sendList") is True
    assert await breaker.before_call("sendText") is False


@pytest.mark.asyncio
async def test_default_endpoint_keys(fake_redis):
    """Calls without an endpoint use the 'default' endpoint keys (backward compat)."""
    breaker = _make_breaker(failure_threshold=3)
    await breaker.record_failure()
    assert await fake_redis.get("circuit:evolution:default:failures") == "1"


# ---------------------------------------------------------------------------
# Soft warning (degraded) before full OPEN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_warning_logged_before_open():
    """At _SOFT_WARNING_THRESHOLD failures (still below failure_threshold) a
    'circuit.degraded' WARNING is emitted and the circuit stays CLOSED."""
    # Need failure_threshold > _SOFT_WARNING_THRESHOLD to see the warning
    breaker = _make_breaker(failure_threshold=5)
    with patch("worker.circuit_breaker.logger") as mock_log:
        await _fail(breaker, _SOFT_WARNING_THRESHOLD)
        # First positional arg is the event name
        events = [c.args[0] for c in mock_log.warning.call_args_list]

    assert "circuit.degraded" in events, f"Events: {events}"
    assert await breaker.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_no_degraded_warning_below_warning_threshold():
    """Below _SOFT_WARNING_THRESHOLD, no degraded warning is emitted."""
    breaker = _make_breaker(failure_threshold=5)
    with patch("worker.circuit_breaker.logger") as mock_log:
        await _fail(breaker, _SOFT_WARNING_THRESHOLD - 1)
        events = [c.kwargs.get("reason") or c.args[0] for c in mock_log.warning.call_args_list]

    assert not any("circuit.degraded" in str(e) for e in events), f"Events: {events}"


# ---------------------------------------------------------------------------
# Exponential backoff
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_effective_timeout_doubles_per_open(fake_redis):
    """Effective recovery doubles with each open and is capped at max_recovery_timeout."""
    breaker = _make_breaker(recovery_timeout=0.05, max_recovery_timeout=7200)

    # First open: open_count=1, effective = 0.05 * 2^0 = 0.05
    await _fail(breaker, breaker.failure_threshold)
    assert await breaker._effective_timeout("default") == 0.05

    # Elapse window -> HALF_OPEN, then fail -> second open (open_count=2)
    await asyncio.sleep(0.06)
    assert await breaker.before_call() is True  # -> HALF_OPEN
    await breaker.record_failure()
    assert await breaker._effective_timeout("default") == 0.10

    # Elapse again -> HALF_OPEN, then fail -> third open (open_count=3)
    await asyncio.sleep(0.11)
    assert await breaker.before_call() is True  # -> HALF_OPEN
    await breaker.record_failure()
    assert await breaker._effective_timeout("default") == 0.20


@pytest.mark.asyncio
async def test_effective_timeout_capped_at_max(fake_redis):
    """Effective timeout should never exceed max_recovery_timeout."""
    # Use base=100 so doubling reaches cap quickly: 100 * 2^7 = 12800 > 7200
    breaker = _make_breaker(recovery_timeout=100, max_recovery_timeout=7200)

    # First open: open_count=1, effective = 100
    await _fail(breaker, breaker.failure_threshold)
    assert await breaker._effective_timeout("default") == 100.0

    # Manually bump open_count to simulate many opens without waiting
    client = redis_queue._ensure_client()
    await client.set("circuit:evolution:default:open_count", 8)
    # effective = 100 * 2^7 = 12800, but capped at 7200
    assert await breaker._effective_timeout("default") == 7200.0


@pytest.mark.asyncio
async def test_open_count_increments_on_reopen(fake_redis):
    """Each open transition bumps open_count, widening the recovery window."""
    breaker = _make_breaker(failure_threshold=2, recovery_timeout=0.05)

    # First open
    await _fail(breaker, 2)
    assert await fake_redis.get("circuit:evolution:default:open_count") == "1"

    # Elapse window -> HALF_OPEN, then fail again -> second open
    await asyncio.sleep(0.06)
    assert await breaker.before_call() is True
    await breaker.record_failure()
    assert await fake_redis.get("circuit:evolution:default:open_count") == "2"


@pytest.mark.asyncio
async def test_success_resets_open_count(fake_redis):
    """A success clears open_count so backoff restarts from the base timeout."""
    breaker = _make_breaker(failure_threshold=2)
    await _fail(breaker, 2)
    assert await fake_redis.get("circuit:evolution:default:open_count") == "1"

    await breaker.record_success_async()
    assert await fake_redis.get("circuit:evolution:default:open_count") is None


# ---------------------------------------------------------------------------
# Integration-style tests with EvolutionClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evolution_client_respects_circuit_breaker():
    """EvolutionClient.send_text_message should check circuit breaker before calling."""
    from worker.evolution_client import CircuitOpenError, EvolutionClient

    with patch("worker.evolution_client.circuit_breaker") as mock_breaker, \
         patch("worker.evolution_client.settings") as mock_settings:

        mock_settings.EVOLUTION_API_URL = "http://test:8080"
        mock_settings.EVOLUTION_API_KEY = "test-key"
        mock_settings.EVOLUTION_INSTANCE_NAME = "test"
        mock_settings.MAX_MESSAGES_PER_MINUTE = 4

        mock_breaker.before_call = AsyncMock(return_value=False)

        client = EvolutionClient()
        with pytest.raises(CircuitOpenError):
            await client.send_text_message("5511999999999", "test")

        mock_breaker.before_call.assert_called_once()


def test_circuit_open_error_is_not_retryable():
    """CircuitOpenError must never be retried - fail fast when the breaker is OPEN."""
    from worker.evolution_client import CircuitOpenError, _is_retryable

    assert _is_retryable(CircuitOpenError("breaker open")) is False


def test_server_errors_remain_retryable():
    """Sanity check: 5xx and connection errors are still retryable."""
    import httpx

    from worker.evolution_client import _is_retryable

    resp = httpx.Response(503, request=httpx.Request("POST", "http://x"))
    assert _is_retryable(httpx.HTTPStatusError("boom", request=resp.request, response=resp)) is True
    assert _is_retryable(httpx.ConnectError("down")) is True
