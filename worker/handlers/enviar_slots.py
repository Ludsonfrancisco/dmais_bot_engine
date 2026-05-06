from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.logs import get_correlation_id, get_logger
from worker.payloads.list_horarios import build_horarios_list

logger = get_logger(__name__)

_MSG_SEM_SLOTS = "Não há horários disponíveis no momento. Nossa equipe entrará em contato em breve."


async def handle(agendamento_id: int, telefone: str) -> None:
    """Busca slots e envia List de horários; se vazio → texto neutro + FALHA ao Django (PRD §4.2)."""
    logger.info("enviar_slots.start", agendamento_id=agendamento_id)

    slots = await django_client.listar_slots(agendamento_id)

    if not slots:
        logger.warning("enviar_slots.no_slots", agendamento_id=agendamento_id)
        await evolution_client.send_text_message(telefone, _MSG_SEM_SLOTS)
        await django_client.post_webhook({
            "event_id": None,
            "agendamento_id": agendamento_id,
            "telefone": telefone,
            "tipo": "FALHA",
            "slot_escolhido": None,
            "raw": None,
            "correlation_id": get_correlation_id(),
        })
        return

    agendamento = {"agendamento_id": agendamento_id, "telefone": telefone}
    payload = build_horarios_list(agendamento, slots)
    await evolution_client.send_list_message(payload)

    logger.info("enviar_slots.done", agendamento_id=agendamento_id, num_slots=len(slots))
