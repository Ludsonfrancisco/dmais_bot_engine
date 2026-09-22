import json as _json

from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.logs import get_correlation_id, get_logger
from worker.payloads.list_horarios import build_horarios_text
from worker.redis_queue import redis_queue

logger = get_logger(__name__)

_MSG_SEM_SLOTS = (
    "Não há horários disponíveis no momento. Nossa equipe entrará em contato em breve."
)
STATE_SLOT_PREFIX = "AGUARDANDO_SLOT:"


async def handle(agendamento_id: int, telefone: str) -> None:
    """Busca slots e envia texto numerado; se vazio → texto neutro + FALHA ao Django."""
    logger.info("enviar_slots.start", agendamento_id=agendamento_id)

    slots = await django_client.listar_slots(agendamento_id)

    if not slots:
        logger.warning("enviar_slots.no_slots", agendamento_id=agendamento_id)
        await evolution_client.send_text_message(telefone, _MSG_SEM_SLOTS)
        await redis_queue.clear_state(telefone)
        await django_client.post_webhook(
            {
                "event_id": None,
                "agendamento_id": agendamento_id,
                "telefone": telefone,
                "tipo": "FALHA",
                "slot_escolhido": None,
                "raw": None,
                "correlation_id": get_correlation_id(),
            }
        )
        return

    agendamento = {"agendamento_id": agendamento_id, "telefone": telefone}
    telefone, texto, mapping = build_horarios_text(agendamento, slots)
    await evolution_client.send_text_message(telefone, texto)
    await redis_queue.set_state(telefone, f"{STATE_SLOT_PREFIX}{_json.dumps(mapping)}")

    logger.info(
        "enviar_slots.done", agendamento_id=agendamento_id, num_slots=len(mapping)
    )
