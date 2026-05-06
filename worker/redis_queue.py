import redis.asyncio as aioredis

from worker.logs import get_logger
from worker.settings import settings

logger = get_logger(__name__)

_TTL = 86400  # 24 horas — TTL padrão para todas as chaves operacionais


class RedisQueue:
    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    def _ensure_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Idempotência de webhook  (PRD §7)
    # chave: evt:<event_id>
    # ------------------------------------------------------------------

    async def is_duplicate_event(self, event_id: str) -> bool:
        """Retorna True se o evento já foi processado (duplicata); False se novo."""
        result = await self._ensure_client().set(
            f"evt:{event_id}", 1, nx=True, ex=_TTL
        )
        # SET NX retorna True se gravou (novo) ou None se já existia (duplicata)
        return result is None

    # ------------------------------------------------------------------
    # Controle de envio inicial  (PRD §7)
    # chave: sent:<agendamento_id>
    # ------------------------------------------------------------------

    async def was_sent(self, agendamento_id: int) -> bool:
        return await self._ensure_client().exists(f"sent:{agendamento_id}") > 0

    async def mark_sent(self, agendamento_id: int) -> None:
        await self._ensure_client().set(f"sent:{agendamento_id}", 1, ex=_TTL)

    # ------------------------------------------------------------------
    # Contador de respostas inválidas  (PRD §7)
    # chave: errors:<chat_id>  — limite de 3 antes de postar FALHA
    # ------------------------------------------------------------------

    async def incr_error(self, chat_id: str) -> int:
        key = f"errors:{chat_id}"
        client = self._ensure_client()
        count = await client.incr(key)
        await client.expire(key, _TTL)  # refresh TTL a cada erro
        return count

    async def reset_error(self, chat_id: str) -> None:
        await self._ensure_client().delete(f"errors:{chat_id}")

    # ------------------------------------------------------------------
    # Fila de retry  (futuro — PRD §7)
    # chave: retry:<queue>
    # ------------------------------------------------------------------

    async def enqueue_retry(self, queue: str, payload: str) -> None:
        await self._ensure_client().lpush(f"retry:{queue}", payload)

    async def dequeue_retry(self, queue: str, timeout: int = 0) -> str | None:
        result = await self._ensure_client().brpop(f"retry:{queue}", timeout=timeout)
        return result[1] if result else None


redis_queue = RedisQueue()
