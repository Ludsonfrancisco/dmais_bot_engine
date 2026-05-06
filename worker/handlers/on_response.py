from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.handlers import enviar_slots
from worker.logs import get_correlation_id, get_logger, new_correlation_id
from worker.payloads.list_initial import build_initial_list
from worker.redis_queue import redis_queue

logger = get_logger(__name__)

_FALLBACK_MSG = "Não entendi sua resposta. Por favor, selecione uma das opções abaixo:"
_VALID_ROW_IDS = frozenset({"CONFIRMAR", "REMARCAR", "JA_ENTREGUE"})
_MAX_ERRORS = 3


# ---------------------------------------------------------------------------
# Helpers de extração do payload da EvolutionAPI
# ---------------------------------------------------------------------------

def _event_id(evt: dict) -> str | None:
    return evt.get("data", {}).get("key", {}).get("id")

def _chat_id(evt: dict) -> str | None:
    return evt.get("data", {}).get("key", {}).get("remoteJid")

def _from_me(evt: dict) -> bool:
    return evt.get("data", {}).get("key", {}).get("fromMe", False)

def _is_upsert(evt: dict) -> bool:
    return evt.get("event") == "messages.upsert"

def _row_id(evt: dict) -> str | None:
    return (
        evt.get("data", {})
           .get("message", {})
           .get("listResponseMessage", {})
           .get("singleSelectReply", {})
           .get("selectedRowId")
    )

def _telefone(chat_id: str) -> str:
    return chat_id.split("@")[0]

def _webhook(event_id, agendamento_id, telefone, tipo, slot_escolhido, raw, cid):
    return {
        "event_id": event_id,
        "agendamento_id": agendamento_id,
        "telefone": telefone,
        "tipo": tipo,
        "slot_escolhido": slot_escolhido,
        "raw": raw,
        "correlation_id": cid,
    }


# ---------------------------------------------------------------------------
# Handler principal
# ---------------------------------------------------------------------------

async def handle(evolution_event: dict) -> None:
    """Processa webhook da EvolutionAPI: idempotência, classificação, roteamento (PRD §4.2)."""
    if not _is_upsert(evolution_event) or _from_me(evolution_event):
        return

    new_correlation_id()

    event_id = _event_id(evolution_event)
    chat_id = _chat_id(evolution_event)

    if not event_id or not chat_id:
        logger.warning("on_response.missing_fields", event=evolution_event.get("event"))
        return

    if await redis_queue.is_duplicate_event(event_id):
        logger.info("on_response.duplicate", event_id=event_id)
        return

    tel = _telefone(chat_id)
    agendamento = await redis_queue.get_agendamento(tel)
    agendamento_id = agendamento["agendamento_id"] if agendamento else None
    cid = get_correlation_id()

    logger.info("on_response.received", event_id=event_id, agendamento_id=agendamento_id)

    row = _row_id(evolution_event)

    if row in _VALID_ROW_IDS:
        if row == "REMARCAR" and agendamento_id is not None:
            await enviar_slots.handle(agendamento_id, tel)
        await django_client.post_webhook(
            _webhook(event_id, agendamento_id, tel, row, None, evolution_event, cid)
        )
        logger.info("on_response.handled", tipo=row, agendamento_id=agendamento_id)

    elif row and row.startswith("SLOT:"):
        slot_iso = row[len("SLOT:"):]
        await django_client.post_webhook(
            _webhook(event_id, agendamento_id, tel, "REMARCAR", slot_iso, evolution_event, cid)
        )
        logger.info("on_response.slot_chosen", slot=slot_iso, agendamento_id=agendamento_id)

    else:
        errors = await redis_queue.incr_error(chat_id)
        logger.info("on_response.invalid", errors=errors, agendamento_id=agendamento_id)
        await django_client.post_webhook(
            _webhook(event_id, agendamento_id, tel, "RESPOSTA_INVALIDA", None, evolution_event, cid)
        )

        if errors >= _MAX_ERRORS:
            await redis_queue.reset_error(chat_id)
            await django_client.post_webhook(
                _webhook(None, agendamento_id, tel, "FALHA", None, None, cid)
            )
            logger.warning("on_response.max_errors_reached", agendamento_id=agendamento_id)
        else:
            await evolution_client.send_text_message(tel, _FALLBACK_MSG)
            if agendamento is not None:
                await evolution_client.send_list_message(build_initial_list(agendamento))
