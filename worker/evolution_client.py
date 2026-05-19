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

from worker.logs import get_logger
from worker.redis_queue import redis_queue
from worker.settings import settings

logger = get_logger(__name__)

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
    redis.call('SET', KEYS[1], tokens)
    redis.call('SET', KEYS[2], now)
    return 1
end
return tostring((1 - tokens) / refill_rate)
"""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError, httpx.RemoteProtocolError))


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

    @_retry
    async def send_list_message(self, payload: dict) -> dict:
        await self.acquire()
        url = f"{settings.EVOLUTION_API_URL}/message/sendList/{settings.EVOLUTION_INSTANCE_NAME}"
        logger.info("evolution.send", telefone=payload.get("number"))
        r = await self._ensure_client().post(url, json=payload)
        r.raise_for_status()
        logger.debug("evolution.send.ok", status=r.status_code)
        return r.json()

    @_retry
    async def send_text_message(self, telefone: str, text: str) -> dict:
        await self.acquire()
        url = f"{settings.EVOLUTION_API_URL}/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}"
        logger.info("evolution.send_text", telefone=telefone)
        r = await self._ensure_client().post(url, json={"number": telefone, "text": text})
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
            logger.warning("evolution.check_exists_failed", telefone=telefone, error=str(exc))
            return True  # em caso de falha, tenta enviar (fail-open)


evolution_client = EvolutionClient()
