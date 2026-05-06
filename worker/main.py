import asyncio
import random
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.handlers import enviar_inicial, on_response, on_timeout
from worker.logs import configure_logging, get_logger, new_correlation_id
from worker.payloads.list_initial import build_initial_list
from worker.redis_queue import redis_queue
from worker.settings import settings

configure_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)


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

                for agendamento in data.get("results", []):
                    status = agendamento.get("status")
                    try:
                        if status == "PENDENTE_CONFIRMACAO":
                            await enviar_inicial.handle(agendamento)
                        elif status == "TIMEOUT":
                            await on_timeout.handle(agendamento["agendamento_id"])
                        # demais status ignorados silenciosamente
                    except Exception as exc:
                        logger.error(
                            "poller.handler_error",
                            status=status,
                            agendamento_id=agendamento.get("agendamento_id"),
                            error=str(exc),
                        )

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
    agendamento = {
        "agendamento_id": 0,
        "nome": body.nome,
        "telefone": body.telefone,
        "data": body.data,
        "hora": body.hora,
        "status": "PENDENTE_CONFIRMACAO",
    }
    payload = build_initial_list(agendamento)
    evolution_response = await evolution_client.send_list_message(payload)
    return {"status": "ok", "evolution_response": evolution_response}
