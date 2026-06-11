import asyncio
import time

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from worker.circuit_breaker import circuit_breaker
from worker.logs import get_logger
from worker.redis_queue import redis_queue
from worker.settings import settings

logger = get_logger(__name__)


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and the call is blocked."""

    pass


_BUCKET_KEY = "ratelimit:bucket"
_LAST_REFILL_KEY = "ratelimit:last_refill"

# Atomic token bucket via Lua: returns int 1 if acquired, or str "-<seconds>" to wait.
_ACQUIRE_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(redis.call('GET', KEYS[1])) or capacity
local last_refill = tonumber(redis.call('GET', KEYS[2])) or now
local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)
if tokens >= 1 then
    tokens = tokens - 1
    redis.call('SET', KEYS[1], tokens, 'EX', 86400)
    redis.call('SET', KEYS[2], now, 'EX', 86400)
    return 1
end
return tostring((1 - tokens) / refill_rate)
"""


# Exceptions that must never be retried — fail fast instead of burning attempts.
# CircuitOpenError means the breaker is OPEN: retrying would just hammer a known
# dead endpoint, so it is skipped immediately.
_NON_RETRYABLE: tuple[type[BaseException], ...] = (CircuitOpenError,)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _NON_RETRYABLE):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ReadError,
            httpx.RemoteProtocolError,
        ),
    )


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "evolution.retry",
        attempt=retry_state.attempt_number,
        exception=str(exc),
    )


_retry = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    before_sleep=_log_retry,
    reraise=True,
)


class EvolutionClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "apikey": settings.EVOLUTION_API_KEY,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def acquire(self) -> None:
        """Block until a rate-limit token is available (token bucket, Redis-backed)."""
        capacity = settings.MAX_MESSAGES_PER_MINUTE
        refill_rate = capacity / 60.0  # tokens per second

        while True:
            now = time.time()
            result = await redis_queue._ensure_client().eval(
                _ACQUIRE_SCRIPT,
                2,
                _BUCKET_KEY,
                _LAST_REFILL_KEY,
                str(capacity),
                str(refill_rate),
                str(now),
            )
            if result == 1:
                logger.debug("ratelimit.acquired")
                return
            wait = float(result)
            logger.debug("ratelimit.wait", wait_seconds=round(wait, 3))
            await asyncio.sleep(wait)

    async def send_list_message(self, payload: dict) -> dict:
        """Send a list message via Evolution API with circuit-breaker protection."""
        if not await circuit_breaker.before_call("sendList"):
            raise CircuitOpenError("circuit breaker is OPEN, skipping send_list")
        try:
            result = await self._send_list_message(payload)
            circuit_breaker.record_success("sendList")
            return result
        except Exception:
            await circuit_breaker.record_failure("sendList")
            raise

    @_retry
    async def _send_list_message(self, payload: dict) -> dict:
        await self.acquire()
        url = f"{settings.EVOLUTION_API_URL}/message/sendList/{settings.EVOLUTION_INSTANCE_NAME}"
        logger.info("evolution.send", telefone=payload.get("number"))
        r = await self._ensure_client().post(url, json=payload)
        r.raise_for_status()
        logger.debug("evolution.send.ok", status=r.status_code)
        return r.json()

    async def send_text_message(self, telefone: str, text: str) -> dict:
        """Send a text message to an individual phone via Evolution API."""
        return await self._send_text_with_circuit(telefone, text, log_field="telefone")

    async def send_group_text_message(self, group_jid: str, text: str) -> dict:
        """Send a text message to a WhatsApp group JID.

        Groups use the same EvolutionAPI sendText endpoint, but the `number`
        payload is a group JID such as `120363000000000000@g.us`. Do not call
        check_exists() for groups; that endpoint is for individual numbers.
        """
        return await self._send_text_with_circuit(
            group_jid, text, log_field="group_jid"
        )

    async def _send_text_with_circuit(
        self, number_or_jid: str, text: str, log_field: str
    ) -> dict:
        if not await circuit_breaker.before_call("sendText"):
            raise CircuitOpenError("circuit breaker is OPEN, skipping send_text")
        try:
            result = await self._send_text_message(
                number_or_jid, text, log_field=log_field
            )
            circuit_breaker.record_success("sendText")
            return result
        except Exception:
            await circuit_breaker.record_failure("sendText")
            raise

    @_retry
    async def _send_text_message(
        self, number_or_jid: str, text: str, log_field: str = "telefone"
    ) -> dict:
        await self.acquire()
        url = f"{settings.EVOLUTION_API_URL}/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}"
        logger.info("evolution.send_text", **{log_field: number_or_jid})
        r = await self._ensure_client().post(
            url, json={"number": number_or_jid, "text": text}
        )
        r.raise_for_status()
        logger.debug("evolution.send_text.ok", status=r.status_code)
        return r.json()

    async def check_exists(self, telefone: str) -> bool:
        """Verifica se o número existe no WhatsApp. Evita 400 + queima de token bucket."""
        url = f"{settings.EVOLUTION_API_URL}/chat/whatsappNumbers/{settings.EVOLUTION_INSTANCE_NAME}"
        try:
            r = await self._ensure_client().post(url, json={"numbers": [telefone]})
            r.raise_for_status()
            data = r.json()
            return bool(data and data[0].get("exists"))
        except Exception as exc:
            logger.warning(
                "evolution.check_exists_failed", telefone=telefone, error=str(exc)
            )
            return True  # em caso de falha, tenta enviar (fail-open)


evolution_client = EvolutionClient()
