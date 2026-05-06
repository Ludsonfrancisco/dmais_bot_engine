from worker.evolution_client import evolution_client
from worker.logs import get_logger, new_correlation_id
from worker.payloads.list_initial import build_initial_list
from worker.redis_queue import redis_queue

logger = get_logger(__name__)


async def handle(agendamento: dict) -> None:
    """Envia List Message inicial para confirmação de coleta (PRD §4.1)."""
    agendamento_id = agendamento["agendamento_id"]
    new_correlation_id()  # correlation_id único por agendamento; injetado nos logs via contextvar

    logger.info("enviar_inicial.start", agendamento_id=agendamento_id)

    if await redis_queue.was_sent(agendamento_id):
        logger.info("enviar_inicial.skip", agendamento_id=agendamento_id)
        return

    payload = build_initial_list(agendamento)
    await evolution_client.send_list_message(payload)
    await redis_queue.mark_sent(agendamento_id)
    await redis_queue.store_agendamento(agendamento["telefone"], agendamento)

    logger.info("enviar_inicial.done", agendamento_id=agendamento_id)
