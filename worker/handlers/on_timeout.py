from worker.api_client import django_client
from worker.logs import get_correlation_id, get_logger, new_correlation_id
from worker.redis_queue import redis_queue

logger = get_logger(__name__)


async def handle(agendamento_id: int) -> None:
    """Posta FALHA no Django e limpa Redis para agendamentos em timeout (PRD §4.3)."""
    new_correlation_id()
    cid = get_correlation_id()

    logger.info("on_timeout.start", agendamento_id=agendamento_id)

    telefone = await redis_queue.get_telefone_by_agendamento_id(agendamento_id)

    await django_client.post_webhook({
        "event_id": None,
        "agendamento_id": agendamento_id,
        "telefone": telefone,
        "tipo": "FALHA",
        "slot_escolhido": None,
        "raw": None,
        "correlation_id": cid,
    })

    await redis_queue.clear_sent(agendamento_id)
    if telefone:
        await redis_queue.clear_agendamento(telefone)

    logger.info("on_timeout.done", agendamento_id=agendamento_id, telefone=telefone)
