import asyncio
import random
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.handlers import enviar_inicial, on_response, on_timeout
from worker.logs import configure_logging, get_logger, new_correlation_id
from worker.redis_queue import redis_queue
from worker.settings import settings

configure_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Adapter Django → shape esperado pelo worker
# ---------------------------------------------------------------------------

def _adapt(raw: dict) -> dict:
    """Converte agendamento do Django (cliente_*, data_agendada, id-UUID) para o shape
    que enviar_inicial / on_response esperam.

    Se data_agendada estiver no passado (planilha desatualizada), usa amanhã
    no lugar para evitar mensagem com data já vencida.
    """
    data_agendada = raw.get("data_agendada", "")
    data_str = data_agendada[:10] if data_agendada else ""

    try:
        if data_str and date.fromisoformat(data_str) < date.today():
            data_str = (date.today() + timedelta(days=1)).isoformat()
    except ValueError:
        pass

    return {
        "agendamento_id": raw.get("id"),                  # UUID string
        "nome":           raw.get("cliente_nome", ""),
        "telefone":       raw.get("cliente_telefone", "").lstrip("+"),
        "data":           data_str,
        "hora":           raw.get("janela_horario", "MANHA"),
        "status":         raw.get("status"),
    }


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

async def _poll_loop() -> None:
    """Ciclo permanente: nunca deve morrer — todas as exceções são capturadas."""
    while True:
        new_correlation_id()
        try:
            page = 1
            while True:
                try:
                    data = await django_client.listar_pendentes(page)
                except Exception as exc:
                    logger.error("poller.fetch_error", page=page, error=str(exc))
                    break

                for raw in data.get("results", []):
                    status = raw.get("status")
                    dispatched = False
                    try:
                        if status == "PENDENTE_CONTATO":
                            result = await enviar_inicial.handle(_adapt(raw))
                            # Só aplica jitter se houve envio real (não em skip por was_sent)
                            dispatched = result != "SKIP"
                        elif status == "TIMEOUT":
                            await on_timeout.handle(raw.get("id"))
                        # demais status ignorados silenciosamente
                    except Exception as exc:
                        logger.error(
                            "poller.handler_error",
                            status=status,
                            agendamento_id=raw.get("id"),
                            error=str(exc),
                        )
                        dispatched = True  # respeita jitter mesmo em falha (anti-burst)

                    if dispatched:
                        # Jitter aleatório (anti-bloqueio WhatsApp): com MAX_MESSAGES_PER_MINUTE=4,
                        # média ~15s, range 8-22s para evitar padrão fixo
                        await asyncio.sleep(random.uniform(8, 22))

                if not data.get("next"):
                    break
                page += 1

        except Exception as exc:
            logger.error("poller.cycle_error", error=str(exc))

        # Jitter ±20% para evitar disparos síncronos quando múltiplos workers subirem
        interval = settings.POLLING_INTERVAL_SECONDS
        jitter = random.uniform(-0.2 * interval, 0.2 * interval)
        await asyncio.sleep(max(1.0, interval + jitter))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_loop(), name="poller")
    logger.info("worker.started", polling_interval=settings.POLLING_INTERVAL_SECONDS)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await django_client.aclose()
        await evolution_client.aclose()
        await redis_queue.aclose()
        logger.info("worker.shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="dmais_bot_engine", lifespan=lifespan)


# ---------------------------------------------------------------------------
# POST /webhook/evolution
# ---------------------------------------------------------------------------

@app.post("/webhook/evolution", status_code=200)
async def webhook_evolution(request: Request):
    event = await request.json()
    await on_response.handle(event)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /health  (PRD §9 + 10.C.24)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    redis_status = "fail"
    evolution_status = "fail"

    try:
        await redis_queue._ensure_client().ping()
        redis_status = "ok"
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                settings.EVOLUTION_API_URL,
                headers={"apikey": settings.EVOLUTION_API_KEY},
            )
            if r.status_code < 500:
                evolution_status = "ok"
    except Exception:
        pass

    return {"status": "ok", "redis": redis_status, "evolution": evolution_status}


# ---------------------------------------------------------------------------
# POST /debug/test-send  (PRD §9 + 10.C.25)
# ---------------------------------------------------------------------------

class _TestSendBody(BaseModel):
    telefone: str
    nome: str
    data: str
    hora: str


@app.post("/debug/test-send")
async def debug_test_send(body: _TestSendBody):
    # agendamento_id sintético único por chamada (evita bloqueio do `was_sent` no Redis)
    import time as _time
    agendamento = {
        "agendamento_id": int(_time.time() * 1000),
        "nome": body.nome,
        "telefone": body.telefone,
        "data": body.data,
        "hora": body.hora,
        "status": "PENDENTE_CONFIRMACAO",
    }
    evolution_response = await enviar_inicial.handle(agendamento)
    return {"status": "ok", "evolution_response": evolution_response}
