"""Redis-backed circuit breaker for Evolution API calls.

States (standard circuit-breaker pattern):
  CLOSED     - normal operation, failures counted
  OPEN       - breaker tripped, skip all calls for recovery_timeout
  HALF_OPEN  - recovery_timeout elapsed, allow 1 test call; success -> CLOSED, failure -> OPEN

Redis keys (TTL 24h), keyed per endpoint:
  circuit:evolution:{endpoint}:state          - CLOSED | OPEN | HALF_OPEN
  circuit:evolution:{endpoint}:failures       - int, consecutive failure count
  circuit:evolution:{endpoint}:last_failure   - epoch timestamp of last failure
  circuit:evolution:{endpoint}:open_count     - int, how many times this endpoint opened (for backoff)
"""

import enum
import time

from worker.logs import get_logger
from worker.redis_queue import redis_queue

logger = get_logger(__name__)

_TTL = 86400  # 24h

_DEFAULT_ENDPOINT = "default"
_SOFT_WARNING_THRESHOLD = 3  # log WARNING before hitting failure_threshold


class CircuitState(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Track consecutive Evolution API failures per endpoint and open/close the circuit."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 900,  # 15 minutes base
        max_recovery_timeout: float = 7200,  # 2 hours cap
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.max_recovery_timeout = max_recovery_timeout

    # ------------------------------------------------------------------
    # Key helpers (per-endpoint)
    # ------------------------------------------------------------------

    @staticmethod
    def _key(endpoint: str, suffix: str) -> str:
        return f"circuit:evolution:{endpoint}:{suffix}"

    async def _effective_timeout(self, endpoint: str) -> float:
        """Compute effective recovery timeout with exponential backoff based on open_count."""
        client = redis_queue._ensure_client()
        open_count = int((await client.get(self._key(endpoint, "open_count")) or 0))
        if open_count <= 0:
            return self.recovery_timeout
        backed = self.recovery_timeout * (2 ** (open_count - 1))
        return min(backed, self.max_recovery_timeout)

    # ------------------------------------------------------------------
    # Public API used by evolution_client & poller
    # ------------------------------------------------------------------

    async def before_call(self, endpoint: str = _DEFAULT_ENDPOINT) -> bool:
        """Return True if the call is allowed, False if the circuit is OPEN.

        Transitions OPEN -> HALF_OPEN when recovery_timeout has elapsed.
        """
        state = await self.get_state(endpoint)

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            effective_timeout = await self._effective_timeout(endpoint)
            last_failure = await self._get_last_failure(endpoint)
            if last_failure is not None and (time.time() - last_failure) >= effective_timeout:
                await self._set_state(endpoint, CircuitState.HALF_OPEN)
                logger.info("circuit.half_open", endpoint=endpoint, recovery_timeout=effective_timeout)
                return True
            logger.warning("circuit.open", endpoint=endpoint, reason="breaker is OPEN, skipping call")
            return False

        # HALF_OPEN - allow exactly one test call
        return True

    def record_success(self, endpoint: str = _DEFAULT_ENDPOINT) -> None:
        """Record a successful call - reset failures and close the circuit."""
        import asyncio
        asyncio.ensure_future(self._record_success_async(endpoint))

    async def record_success_async(self, endpoint: str = _DEFAULT_ENDPOINT) -> None:
        """Async version for callers that want to await."""
        await self._record_success_async(endpoint)

    async def record_failure(self, endpoint: str = _DEFAULT_ENDPOINT) -> None:
        """Increment failure counter. Trip to OPEN when threshold reached."""
        client = redis_queue._ensure_client()
        pipe = client.pipeline()
        pipe.incr(self._key(endpoint, "failures"))
        pipe.set(self._key(endpoint, "last_failure"), time.time(), ex=_TTL)
        await pipe.execute()

        failures = int(await client.get(self._key(endpoint, "failures")) or 0)
        state = await self.get_state(endpoint)

        # Soft warning: log degradation before full trip
        if failures == _SOFT_WARNING_THRESHOLD and state == CircuitState.CLOSED:
            logger.warning(
                "circuit.degraded",
                endpoint=endpoint,
                consecutive_failures=failures,
                threshold=self.failure_threshold,
                reason="approaching circuit break threshold",
            )

        if state == CircuitState.HALF_OPEN:
            # Any failure in half-open goes straight back to open
            await self._increment_open_count(endpoint)
            await self._set_state(endpoint, CircuitState.OPEN)
            effective_timeout = await self._effective_timeout(endpoint)
            logger.warning(
                "circuit.re_opened",
                endpoint=endpoint,
                recovery_timeout=effective_timeout,
                reason="failure in HALF_OPEN state",
            )
            return

        if failures >= self.failure_threshold:
            await self._increment_open_count(endpoint)
            await self._set_state(endpoint, CircuitState.OPEN)
            effective_timeout = await self._effective_timeout(endpoint)
            logger.warning(
                "circuit.opened",
                endpoint=endpoint,
                consecutive_failures=failures,
                threshold=self.failure_threshold,
                recovery_timeout=effective_timeout,
            )

    async def is_open(self, endpoint: str = _DEFAULT_ENDPOINT) -> bool:
        """Convenience: is the circuit currently blocking calls?"""
        state = await self.get_state(endpoint)
        if state == CircuitState.OPEN:
            effective_timeout = await self._effective_timeout(endpoint)
            last_failure = await self._get_last_failure(endpoint)
            if last_failure is not None and (time.time() - last_failure) >= effective_timeout:
                await self._set_state(endpoint, CircuitState.HALF_OPEN)
                return False
            return True
        return False

    async def get_state(self, endpoint: str = _DEFAULT_ENDPOINT) -> CircuitState:
        """Read the current circuit state from Redis."""
        client = redis_queue._ensure_client()
        val = await client.get(self._key(endpoint, "state"))
        if val is None:
            return CircuitState.CLOSED
        try:
            return CircuitState(val)
        except ValueError:
            return CircuitState.CLOSED

    async def reset(self, endpoint: str = _DEFAULT_ENDPOINT) -> None:
        """Force-reset the breaker to CLOSED (useful for manual recovery)."""
        client = redis_queue._ensure_client()
        pipe = client.pipeline()
        pipe.set(self._key(endpoint, "state"), CircuitState.CLOSED.value, ex=_TTL)
        pipe.set(self._key(endpoint, "failures"), 0, ex=_TTL)
        pipe.delete(self._key(endpoint, "last_failure"))
        pipe.delete(self._key(endpoint, "open_count"))
        await pipe.execute()
        logger.info("circuit.reset", endpoint=endpoint, reason="manual reset")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _set_state(self, endpoint: str, state: CircuitState) -> None:
        await redis_queue._ensure_client().set(self._key(endpoint, "state"), state.value, ex=_TTL)

    async def _get_last_failure(self, endpoint: str) -> float | None:
        val = await redis_queue._ensure_client().get(self._key(endpoint, "last_failure"))
        return float(val) if val else None

    async def _increment_open_count(self, endpoint: str) -> None:
        client = redis_queue._ensure_client()
        await client.incr(self._key(endpoint, "open_count"))
        await client.expire(self._key(endpoint, "open_count"), _TTL)

    async def _record_success_async(self, endpoint: str) -> None:
        client = redis_queue._ensure_client()
        pipe = client.pipeline()
        pipe.set(self._key(endpoint, "state"), CircuitState.CLOSED.value, ex=_TTL)
        pipe.set(self._key(endpoint, "failures"), 0, ex=_TTL)
        pipe.delete(self._key(endpoint, "open_count"))
        await pipe.execute()
        logger.info("circuit.closed", endpoint=endpoint, reason="success recorded")


# Module-level singleton used by evolution_client and main poller
circuit_breaker = CircuitBreaker()
