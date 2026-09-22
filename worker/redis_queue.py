import json as _json
import time as _time

import redis.asyncio as aioredis

from worker.logs import get_logger
from worker.settings import settings

logger = get_logger(__name__)

_TIMEOUT_WATCH = "timeout_watch"  # sorted set: member=telefone, score=deadline_ts

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
        result = await self._ensure_client().set(f"evt:{event_id}", 1, nx=True, ex=_TTL)
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
    # Cache de agendamento por telefone  (on_response needs agendamento_id)
    # chave: agendamento:<telefone>  — JSON do dict completo
    # ------------------------------------------------------------------

    async def store_agendamento(self, telefone: str, agendamento: dict) -> None:
        agendamento_id = agendamento.get("agendamento_id")
        client = self._ensure_client()
        pipe = client.pipeline()
        pipe.set(f"agendamento:{telefone}", _json.dumps(agendamento), ex=_TTL)
        if agendamento_id is not None:
            # índice reverso: agendamento_id → telefone (usado por on_timeout)
            pipe.set(f"agendamento_id:{agendamento_id}", telefone, ex=_TTL)
        await pipe.execute()

    async def get_agendamento(self, telefone: str) -> dict | None:
        val = await self._ensure_client().get(f"agendamento:{telefone}")
        return _json.loads(val) if val else None

    async def get_telefone_by_agendamento_id(self, agendamento_id: int) -> str | None:
        return await self._ensure_client().get(f"agendamento_id:{agendamento_id}")

    async def clear_sent(self, agendamento_id: int) -> None:
        await self._ensure_client().delete(f"sent:{agendamento_id}")

    async def clear_agendamento(self, telefone: str) -> None:
        agendamento_id_val = None
        data = await self._ensure_client().get(f"agendamento:{telefone}")
        if data:
            agendamento_id_val = _json.loads(data).get("agendamento_id")
        client = self._ensure_client()
        pipe = client.pipeline()
        pipe.delete(f"agendamento:{telefone}")
        if agendamento_id_val is not None:
            pipe.delete(f"agendamento_id:{agendamento_id_val}")
        await pipe.execute()

    # ------------------------------------------------------------------
    # Estado da conversa por telefone  (substitui rowId das listMessages)
    # chave: state:<telefone>  — valores: "AGUARDANDO_INICIAL" | "AGUARDANDO_SLOT:<json>"
    # ------------------------------------------------------------------

    async def set_state(self, telefone: str, state: str) -> None:
        await self._ensure_client().set(f"state:{telefone}", state, ex=_TTL)

    async def get_state(self, telefone: str) -> str | None:
        return await self._ensure_client().get(f"state:{telefone}")

    async def clear_state(self, telefone: str) -> None:
        await self._ensure_client().delete(f"state:{telefone}")

    # ------------------------------------------------------------------
    # Timeout tracking  (conversation inactivity detection)
    # sorted set: timeout_watch  — member=telefone, score=deadline_ts
    # string:     activity:<telefone>  — last activity epoch timestamp
    # ------------------------------------------------------------------

    async def track_activity(self, telefone: str) -> None:
        """Atualiza timestamp de atividade e recalcula deadline no sorted set.

        Score = now + CONVERSATION_TIMEOUT_SECONDS.
        """
        now = _time.time()
        deadline = now + settings.CONVERSATION_TIMEOUT_SECONDS
        client = self._ensure_client()
        pipe = client.pipeline()
        pipe.set(f"activity:{telefone}", str(now), ex=_TTL)
        pipe.zadd(_TIMEOUT_WATCH, {telefone: deadline})
        await pipe.execute()

    async def clear_activity(self, telefone: str) -> None:
        """Remove rastreamento de atividade e entry do sorted set."""
        client = self._ensure_client()
        pipe = client.pipeline()
        pipe.delete(f"activity:{telefone}")
        pipe.zrem(_TIMEOUT_WATCH, telefone)
        await pipe.execute()

    async def scan_timeouts(self) -> list[str]:
        """Retorna telefones cujo deadline já passou (score <= now)."""
        now = _time.time()
        members = await self._ensure_client().zrangebyscore(_TIMEOUT_WATCH, "-inf", now)
        return members  # list[str]

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
