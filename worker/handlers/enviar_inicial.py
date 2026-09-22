from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.logs import get_correlation_id, get_logger, new_correlation_id
from worker.payloads.list_initial import build_initial_text
from worker.redis_queue import redis_queue

logger = get_logger(__name__)

STATE_INICIAL = "AGUARDANDO_INICIAL"


async def handle(agendamento: dict) -> dict | None:
    """Envia mensagem inicial (3 opções) e marca estado AGUARDANDO_INICIAL.

    Antes de enviar, verifica se o número existe no WhatsApp. Se não existir,
    posta FALHA pro Django e marca como sent para não retentar.
    """
    agendamento_id = agendamento["agendamento_id"]
    telefone = agendamento["telefone"]
    new_correlation_id()

    logger.info(
        "enviar_inicial.start", agendamento_id=agendamento_id, telefone=telefone
    )

    if await redis_queue.was_sent(agendamento_id):
        logger.info("enviar_inicial.skip", agendamento_id=agendamento_id)
        return "SKIP"  # sinaliza ao poller que não houve envio real (pula jitter)

    # Pre-check: evita 400 da Evolution e queima de token bucket
    if not await evolution_client.check_exists(telefone):
        logger.warning(
            "enviar_inicial.number_not_on_whatsapp",
            agendamento_id=agendamento_id,
            telefone=telefone,
        )
        await redis_queue.mark_sent(agendamento_id)  # impede reprocessar
        try:
            await django_client.post_webhook(
                {
                    "event_id": None,
                    "agendamento_id": agendamento_id,
                    "telefone": telefone,
                    "tipo": "FALHA",
                    "slot_escolhido": None,
                    "raw": {"motivo": "numero_nao_existe_whatsapp"},
                    "correlation_id": get_correlation_id(),
                }
            )
        except Exception as exc:
            logger.warning("django.webhook_failed_on_falha", error=str(exc))
        return None

    telefone, texto = build_initial_text(agendamento)
    await redis_queue.store_agendamento(telefone, agendamento)
    await redis_queue.set_state(telefone, STATE_INICIAL)
    await redis_queue.mark_sent(agendamento_id)
    response = await evolution_client.send_text_message(telefone, texto)

    # Transição no kanban: PENDENTE_CONTATO → AGUARDANDO_CLIENTE + incrementa tentativas
    try:
        await django_client.update_status(
            agendamento_id,
            "AGUARDANDO_CLIENTE",
            motivo="Mensagem inicial enviada pelo motor",
            inc_tentativas=True,
        )
    except Exception as exc:
        logger.warning(
            "django.status_patch_failed", agendamento_id=agendamento_id, error=str(exc)
        )

    logger.info("enviar_inicial.done", agendamento_id=agendamento_id, telefone=telefone)
    return response
