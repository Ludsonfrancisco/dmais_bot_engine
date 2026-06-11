import asyncio
import base64
import random
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

from worker.api_client import django_client
from worker.circuit_breaker import circuit_breaker
from worker.evolution_client import CircuitOpenError, evolution_client
from worker.handlers import (
    enviar_inicial,
    on_conversation_timeout,
    on_response,
    on_timeout,
)
from worker.handlers.on_response import cleanup_chat_locks
from worker.logs import configure_logging, get_logger, new_correlation_id
from worker.redis_queue import redis_queue
from worker.reports.screenshots import capture_portal_page
from worker.reports.sender import send_report_screenshot, send_report_text
from worker.settings import settings
from worker.reports.formatter import format_cycle_report, format_morning_message
from worker.reports.stats import get_deltas, save_snapshot
from worker.reports.data import (
    fetch_city_group_counts,
    fetch_group_counts,
    fetch_status_header,
)

configure_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)

# When the circuit is OPEN, poll again sooner than the full interval so the
# breaker can transition to HALF_OPEN and recover quickly once Evolution is back.
_CIRCUIT_OPEN_RETRY_SECONDS = 30


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
        "agendamento_id": raw.get("id"),  # UUID string
        "nome": raw.get("cliente_nome", ""),
        "telefone": raw.get("cliente_telefone", "").lstrip("+"),
        "data": data_str,
        "hora": raw.get("janela_horario", "MANHA"),
        "status": raw.get("status"),
    }


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------


async def _poll_loop() -> None:
    """Ciclo permanente: nunca deve morrer — todas as exceções são capturadas."""
    cleanup_counter = 0
    while True:
        new_correlation_id()
        try:
            # Timeout scan: check for conversations that expired due to inactivity
            try:
                timed_out = await redis_queue.scan_timeouts()
                for telefone in timed_out:
                    try:
                        await on_conversation_timeout.handle(telefone)
                    except Exception as exc:
                        logger.error(
                            "poller.timeout_handler_error",
                            telefone=telefone,
                            error=str(exc),
                        )
            except Exception as exc:
                logger.error("poller.timeout_scan_error", error=str(exc))

            # Periodic chat-lock cleanup: every 10 cycles, remove idle locks
            cleanup_counter += 1
            if cleanup_counter >= 10:
                try:
                    cleanup_chat_locks()
                except Exception as exc:
                    logger.error("poller.lock_cleanup_error", error=str(exc))
                cleanup_counter = 0

            # Circuit breaker check: skip entire poll cycle if Evolution API is down.
            # The poller dispatches via send_text_message, so it watches the
            # 'sendText' endpoint specifically.
            # Retry sooner than the full interval so recovery (HALF_OPEN) happens fast.
            if await circuit_breaker.is_open("sendText"):
                logger.warning(
                    "poller.skip",
                    reason="circuit open, retrying soon",
                    retry_in=_CIRCUIT_OPEN_RETRY_SECONDS,
                )
                await asyncio.sleep(_CIRCUIT_OPEN_RETRY_SECONDS)
                continue

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
                    except CircuitOpenError:
                        logger.warning(
                            "poller.circuit_open",
                            status=status,
                            agendamento_id=raw.get("id"),
                        )
                        dispatched = False  # don't jitter, skip to next item
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


# ---------------------------------------------------------------------------
# POST /reports/debug-send-text  (Sprint Report Automation)
# ---------------------------------------------------------------------------


class _ReportDebugTextBody(BaseModel):
    text: str = "Teste de envio do dmais_bot_engine para o grupo de homologação."


@app.post("/reports/debug-send-text")
async def debug_send_report_text(body: _ReportDebugTextBody):
    results = await send_report_text(body.text)
    return {"status": "ok", "sent": results}


# ---------------------------------------------------------------------------
# POST /reports/debug-screenshot  (Sprint 2 — Print autenticado do portal)
# ---------------------------------------------------------------------------


class _ReportDebugScreenshotBody(BaseModel):
    path: str = "/backlog/"
    viewport_width: int = 1280
    viewport_height: int = 720
    element_selector: str | None = None
    select_value: str | None = None
    row_dim: str | None = None
    col_dim: str | None = None
    font_scale: float = 1.0
    light_mode: bool = False


@app.post("/reports/debug-screenshot")
async def debug_screenshot(body: _ReportDebugScreenshotBody):
    screenshot_bytes = await capture_portal_page(
        body.path,
        viewport_width=body.viewport_width,
        viewport_height=body.viewport_height,
        element_selector=body.element_selector,
        select_value=body.select_value,
        row_dim=body.row_dim,
        col_dim=body.col_dim,
        font_scale=body.font_scale,
        light_mode=body.light_mode,
    )
    return {
        "status": "ok",
        "path": body.path,
        "size_bytes": len(screenshot_bytes),
        "image_base64": base64.b64encode(screenshot_bytes).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# POST /reports/debug-send-screenshot  (Sprint 3)
# ---------------------------------------------------------------------------


class _ReportDebugSendScreenshotBody(BaseModel):
    path: str = "/backlog/"
    caption: str = ""
    viewport_width: int = 1280
    viewport_height: int = 720
    element_selector: str | None = None
    row_dim: str | None = None
    col_dim: str | None = None
    light_mode: bool = False


@app.post("/reports/debug-send-screenshot")
async def debug_send_screenshot(body: _ReportDebugSendScreenshotBody):
    screenshot_bytes = await capture_portal_page(
        body.path,
        viewport_width=body.viewport_width,
        viewport_height=body.viewport_height,
        element_selector=body.element_selector,
        row_dim=body.row_dim,
        col_dim=body.col_dim,
        light_mode=body.light_mode,
    )
    results = await send_report_screenshot(screenshot_bytes, caption=body.caption)
    return {"status": "ok", "sent": results}


# ---------------------------------------------------------------------------
# POST /reports/debug-morning  (Sprint 4 — Mensagem da manhã)
# ---------------------------------------------------------------------------


@app.post("/reports/debug-morning")
async def debug_morning():
    from worker.evolution_client import evolution_client
    from worker.reports.destinations import get_report_destinations

    text = format_morning_message()
    results = []
    for dest in get_report_destinations():
        resp = await evolution_client.send_group_text_message(dest.group_jid, text)
        results.append({"target": dest.name, "response": resp})
    return {"status": "ok", "sent": results}


# ---------------------------------------------------------------------------
# POST /reports/debug-cycle  (Sprint 4 — Ciclo completo)
# ---------------------------------------------------------------------------


class _DebugCycleBody(BaseModel):
    hour: str = "06:10"


@app.post("/reports/debug-cycle")
async def debug_cycle(body: _DebugCycleBody):

    # Launch a single browser session for everything
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1920, "height": 720})
        page = await ctx.new_page()

        # Login
        await page.goto(f"{settings.DMAIS_PORTAL_URL}/login/", wait_until="networkidle")
        await page.fill('input[type="email"]', settings.DMAIS_PORTAL_EMAIL)
        await page.fill('input[type="password"]', settings.DMAIS_PORTAL_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)

        # Fetch portal data
        status = await fetch_status_header(page)
        group_counts = await fetch_group_counts(page)
        city_counts = await fetch_city_group_counts(page)

        # Calculate deltas
        deltas = await get_deltas(group_counts, city_counts)

        # Save current snapshot for next cycle
        await save_snapshot(group_counts, city_counts)

        await browser.close()

    # Format report
    entrante = status.get("ultima_atualizacao_abertura", "--:--")
    download = status.get("ultimo_download", "--:--")
    text = format_cycle_report(
        body.hour,
        entrante,
        download,
        group_counts,
        deltas["groups"],
        deltas["cities"],
        deltas["has_previous"],
    )

    # Send 3 prints first, then text report
    prints = [
        {
            "path": "/backlog/",
            "vw": 1920,
            "vh": 1170,
            "el": "#matrix-inner",
            "row": "cidade",
            "col": "grupo",
            "cap": "*BACKLOG DMAIS (Todas as Cidades)*",
        },
        {
            "path": "/backlog/",
            "vw": 1920,
            "vh": 720,
            "el": "#matrix-inner",
            "row": "cidade_grupo",
            "col": None,
            "cap": "*BACKLOG DMAIS (Área Dmais)*",
        },
        {
            "path": "/backlog/",
            "vw": 1920,
            "vh": 720,
            "el": "#abortados-inner",
            "row": None,
            "col": None,
            "cap": "*REPAROS ABORTADOS*",
            "light": True,
        },
    ]

    for prt in prints:
        img = await capture_portal_page(
            prt["path"],
            viewport_width=prt["vw"],
            viewport_height=prt["vh"],
            element_selector=prt["el"],
            row_dim=prt.get("row"),
            col_dim=prt.get("col"),
            light_mode=prt.get("light", False),
        )
        await send_report_screenshot(img, caption=prt["cap"])

    # Send text report after prints (without test prefix)
    from worker.evolution_client import evolution_client
    from worker.reports.destinations import get_report_destinations

    results = []
    for dest in get_report_destinations():
        resp = await evolution_client.send_group_text_message(dest.group_jid, text)
        results.append({"target": dest.name, "response": resp})

    return {"status": "ok", "report_sent": results, "prints_sent": len(prints)}
