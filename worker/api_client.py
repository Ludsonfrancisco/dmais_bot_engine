import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from worker.logs import get_logger
from worker.settings import settings

logger = get_logger(__name__)


def _is_retryable(exc: BaseException) -> bool:
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
        "django.retry",
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


class DjangoAPIClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Token {settings.DJANGO_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @_retry
    async def listar_pendentes(self, page: int) -> dict:
        url = f"{settings.DJANGO_API_BASE_URL}/api/logistica-reversa/pendentes-recolha/"
        logger.debug("django.get", url=url, page=page)
        r = await self._ensure_client().get(url, params={"page": page})
        r.raise_for_status()
        logger.debug("django.get.ok", url=url, status=r.status_code)
        return r.json()

    @_retry
    async def listar_slots(self, agendamento_id: int) -> list[dict]:
        url = f"{settings.DJANGO_API_BASE_URL}/api/logistica-reversa/slots/{agendamento_id}/"
        logger.debug("django.get", url=url, agendamento_id=agendamento_id)
        r = await self._ensure_client().get(url)
        r.raise_for_status()
        logger.debug("django.get.ok", url=url, status=r.status_code)
        return r.json()

    @_retry
    async def post_webhook(self, payload: dict) -> None:
        url = f"{settings.DJANGO_API_BASE_URL}/api/logistica-reversa/whatsapp-webhook/"
        logger.info(
            "django.webhook",
            url=url,
            tipo=payload.get("tipo"),
            agendamento_id=payload.get("agendamento_id"),
        )
        r = await self._ensure_client().post(url, json=payload)
        r.raise_for_status()
        logger.debug("django.webhook.ok", url=url, status=r.status_code)

    @_retry
    async def update_status(
        self,
        agendamento_id: str,
        novo_status: str,
        motivo: str = "",
        inc_tentativas: bool = False,
    ) -> None:
        """PATCH no endpoint de status para transicionar o agendamento no kanban.

        Se `inc_tentativas` for True, também incrementa o contador tentativas_envio.
        """
        url = f"{settings.DJANGO_API_BASE_URL}/api/logistica-reversa/agendamentos/{agendamento_id}/status/"
        logger.info(
            "django.status_patch",
            agendamento_id=agendamento_id,
            status=novo_status,
            inc_tentativas=inc_tentativas,
        )
        r = await self._ensure_client().patch(
            url,
            json={
                "status": novo_status,
                "motivo": motivo,
                "inc_tentativas": inc_tentativas,
            },
        )
        r.raise_for_status()
        logger.debug("django.status_patch.ok", status=r.status_code)


django_client = DjangoAPIClient()
