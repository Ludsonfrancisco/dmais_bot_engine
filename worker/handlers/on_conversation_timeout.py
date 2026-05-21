from worker.api_client import django_client
from worker.handlers.enviar_inicial import STATE_INICIAL
from worker.logs import get_correlation_id, get_logger, new_correlation_id
from worker.redis_queue import redis_queue

logger = get_logger(__name__)


async def handle(telefone: str) -> None:
    """Posta FALHA no Django e limpa Redis para conversas que expiraram por inatividade.

    Só processa se o estado atual NÃO for AGUARDANDO_INICIAL (i.e., mid-flow).
    Se estiver no estado inicial, apenas limpa o tracking sem postar FALHA.
    """
    new_correlation_id()
    cid = get_correlation_id()

    logger.info("on_conversation_timeout.start", telefone=telefone)

    state = await redis_queue.get_state(telefone) or ""

    if state == STATE_INICIAL:
        # Usuario nunca respondeu, só limpamos o tracking — Django já vai
        # reapresentar como PENDENTE_CONTATO no proximo poll.
        logger.info("on_conversation_timeout.skip_initial_state", telefone=telefone)
        await redis_queue.clear_activity(telefone)
        return

    # Mid-flow: usuario respondeu pelo menos uma vez mas parou de responder.
    agendamento = await redis_queue.get_agendamento(telefone)
    agendamento_id = agendamento["agendamento_id"] if agendamento else None

    await django_client.post_webhook({
        "event_id": None,
        "agendamento_id": agendamento_id,
        "telefone": telefone,
        "tipo": "FALHA",
        "slot_escolhido": None,
        "raw": {"motivo": "timeout_conversa"},
        "correlation_id": cid,
    })

    await redis_queue.clear_state(telefone)
    await redis_queue.clear_agendamento(telefone)
    await redis_queue.clear_activity(telefone)

    logger.info(
        "on_conversation_timeout.done",
        telefone=telefone,
        agendamento_id=agendamento_id,
    )
