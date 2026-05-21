import asyncio
import json as _json
import unicodedata

from worker.api_client import django_client
from worker.evolution_client import evolution_client
from worker.handlers.enviar_inicial import STATE_INICIAL
from worker.logs import get_correlation_id, get_logger, new_correlation_id
from worker.payloads.list_initial import (
    MSG_JA_ENTREGUE_PERGUNTA,
    OPCOES_INICIAIS,
    PERIODOS,
    build_datas_remarcar_text,
    build_initial_text,
    build_periodo_text,
    slot_iso_de,
)
from worker.redis_queue import redis_queue

logger = get_logger(__name__)

_FALLBACK_PREFIX = "Desculpe, não entendi sua resposta. 🙏\n\n"
_MAX_ERRORS = 3

# Estados (prefixo + JSON opcional como contexto)
STATE_AGUARDANDO_PERIODO          = "AGUARDANDO_PERIODO:"           # ctx: {"data": "YYYY-MM-DD"}
STATE_AGUARDANDO_DATA_REMARCAR    = "AGUARDANDO_DATA_REMARCAR:"     # ctx: {"1": "YYYY-MM-DD", ...}
STATE_AGUARDANDO_PERIODO_REMARCAR = "AGUARDANDO_PERIODO_REMARCAR:"  # ctx: {"data": "YYYY-MM-DD"}
STATE_AGUARDANDO_TEXTO_ENTREGUE   = "AGUARDANDO_TEXTO_ENTREGUE"     # sem ctx

# Numérico → ID lógico inicial (CONFIRMAR/REMARCAR/JA_ENTREGUE)
_NUM_TO_INITIAL = {str(i): _id for i, (_id, _) in enumerate(OPCOES_INICIAIS, start=1)}
# Written-out numbers (Portuguese) → same mapping
_NUM_EXTENSO_TO_INITIAL = {
    "um": "CONFIRMAR", "dois": "REMARCAR", "tres": "JA_ENTREGUE",
    "três": "JA_ENTREGUE",
}
# Numérico → ID período (MANHA/TARDE)
_NUM_TO_PERIODO = {str(i): _id for i, (_id, _) in enumerate(PERIODOS, start=1)}
# Written-out numbers (Portuguese) → same mapping
_NUM_EXTENSO_TO_PERIODO = {
    "um": "MANHA", "dois": "TARDE",
}

_KEYWORD_TO_INITIAL = {
    "confirmar": "CONFIRMAR", "confirmo": "CONFIRMAR", "sim": "CONFIRMAR",
    "remarcar": "REMARCAR",   "remarca": "REMARCAR",   "trocar": "REMARCAR",
    "ja entreguei": "JA_ENTREGUE", "entreguei": "JA_ENTREGUE",
}
_KEYWORD_TO_PERIODO = {
    "manha": "MANHA", "manhã": "MANHA",
    "tarde": "TARDE",
}

# Replies conversacionais (personalizadas por opção, com branding AT3)
_REPLY_CONFIRMADO_TPL = (
    "✅ A AT3 Internet agradece a sua confirmação!\n\n"
    "Nosso técnico passará no dia *{data_humana}* no período da *{periodo_humano}* "
    "para realizar a coleta do equipamento.\n\n"
    "Caso precise alterar, é só nos avisar. Tenha um ótimo dia! 🙌"
)
_REPLY_REMARCADO_TPL = (
    "✅ A AT3 Internet agradece!\n\n"
    "Sua coleta foi remarcada com sucesso. Nosso técnico passará no dia "
    "*{data_humana}* no período da *{periodo_humano}*.\n\n"
    "Caso precise alterar novamente, é só nos avisar. Tenha um ótimo dia! 🙌"
)
_REPLY_JA_ENTREGUE = (
    "🙏 A AT3 Internet agradece a informação!\n\n"
    "Vamos atualizar nosso sistema com os dados que você nos passou. "
    "Tenha um ótimo dia! 🙌"
)

_PERIODO_LABEL = {"MANHA": "manhã", "TARDE": "tarde"}

# Locks por chat para serializar mensagens em rajada do mesmo cliente.
# Single-process asyncio: get/set síncronos não correm, então não precisa meta-lock.
_chat_locks: dict[str, asyncio.Lock] = {}
_CHAT_LOCK_TTL = 3600  # seconds before an idle lock is considered stale


def _get_chat_lock(chat_id: str) -> asyncio.Lock:
    lock = _chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[chat_id] = lock
    return lock


def cleanup_chat_locks() -> int:
    """Remove stale locks that are not currently held.

    Returns the number of locks removed. Safe to call periodically from the
    poller to prevent unbounded dict growth from one-off chats.
    """
    stale = [
        cid for cid, lock in _chat_locks.items()
        if not lock.locked()
    ]
    for cid in stale:
        _chat_locks.pop(cid, None)
    if stale:
        logger.info("on_response.lock_cleanup", removed=len(stale), remaining=len(_chat_locks))
    return len(stale)


# ---------------------------------------------------------------------------
# Helpers de extração do payload da EvolutionAPI
# ---------------------------------------------------------------------------

def _event_id(evt: dict) -> str | None:
    return evt.get("data", {}).get("key", {}).get("id")

def _chat_id(evt: dict) -> str | None:
    """Retorna o JID do contato. Se for @lid (anonimizado pelo WhatsApp Multi-Device),
    prioriza remoteJidAlt que carrega o número real em formato @s.whatsapp.net."""
    key = evt.get("data", {}).get("key", {}) or {}
    raw = key.get("remoteJid")
    if raw and raw.endswith("@lid"):
        alt = key.get("remoteJidAlt")
        if alt:
            return alt
    return raw

def _from_me(evt: dict) -> bool:
    return evt.get("data", {}).get("key", {}).get("fromMe", False)

def _is_upsert(evt: dict) -> bool:
    return evt.get("event") == "messages.upsert"

def _message_text(evt: dict) -> str | None:
    msg = evt.get("data", {}).get("message", {}) or {}
    txt = msg.get("conversation")
    if txt:
        return txt
    return (msg.get("extendedTextMessage") or {}).get("text")

def _telefone(chat_id: str) -> str:
    return chat_id.split("@")[0]

def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())

def _classify_initial(text: str) -> str | None:
    norm = _normalize(text)
    if norm in _NUM_TO_INITIAL:
        return _NUM_TO_INITIAL[norm]
    if norm in _NUM_EXTENSO_TO_INITIAL:
        return _NUM_EXTENSO_TO_INITIAL[norm]
    return _KEYWORD_TO_INITIAL.get(norm)

def _classify_periodo(text: str) -> str | None:
    norm = _normalize(text)
    if norm in _NUM_TO_PERIODO:
        return _NUM_TO_PERIODO[norm]
    if norm in _NUM_EXTENSO_TO_PERIODO:
        return _NUM_EXTENSO_TO_PERIODO[norm]
    return _KEYWORD_TO_PERIODO.get(norm)

def _format_data_humana(data_str: str) -> str:
    from datetime import date as _date
    dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    try:
        d = _date.fromisoformat(data_str)
        return f"{dias[d.weekday()]}, {d.strftime('%d/%m')}"
    except (ValueError, TypeError):
        return data_str

def _state_ctx(state: str, prefix: str) -> dict:
    """Decodifica JSON após o prefixo do estado. Retorna {} se vazio/erro."""
    raw = state[len(prefix):]
    if not raw:
        return {}
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        logger.warning("on_response.bad_state_json", state=state)
        return {}

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


async def _post_webhook_safe(payload: dict) -> None:
    """Posta webhook ao Django; loga e absorve falhas para não bloquear o reply ao usuário."""
    try:
        await django_client.post_webhook(payload)
    except Exception as exc:
        logger.warning(
            "django.webhook_failed",
            tipo=payload.get("tipo"),
            agendamento_id=payload.get("agendamento_id"),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Handler principal
# ---------------------------------------------------------------------------

async def handle(evolution_event: dict) -> None:
    """State machine multi-etapas: inicial → período/datas → confirmação.

    Lock por chat_id serializa mensagens em rajada do mesmo cliente.
    """
    if not _is_upsert(evolution_event) or _from_me(evolution_event):
        return

    new_correlation_id()

    event_id = _event_id(evolution_event)
    chat_id = _chat_id(evolution_event)

    if not event_id or not chat_id:
        logger.warning("on_response.missing_fields", event=evolution_event.get("event"))
        return

    # Ignora chats que não são conversas 1-a-1 (grupos, newsletter, broadcast)
    if chat_id.endswith(("@g.us", "@newsletter", "@broadcast")):
        return

    # Serializa: se chegarem várias msgs em rajada do mesmo chat, processa uma de cada vez
    async with _get_chat_lock(chat_id):
        await _handle_locked(evolution_event, event_id, chat_id)


async def _handle_locked(evolution_event: dict, event_id: str, chat_id: str) -> None:
    if await redis_queue.is_duplicate_event(event_id):
        logger.info("on_response.duplicate", event_id=event_id)
        return

    tel = _telefone(chat_id)
    agendamento = await redis_queue.get_agendamento(tel)
    agendamento_id = agendamento["agendamento_id"] if agendamento else None
    cid = get_correlation_id()
    state = await redis_queue.get_state(tel) or ""
    text = _message_text(evolution_event)

    logger.info(
        "on_response.received",
        event_id=event_id,
        chat_id=chat_id,
        agendamento_id=agendamento_id,
        state=state[:40],
        has_text=bool(text),
        text_preview=(text or "")[:50],
    )

    if not text:
        return  # mídia/sticker → ignora sem erro

    # ──────────────────────────────────────────────────────────────
    # Estado: aguardando texto livre (Já entreguei)
    # ──────────────────────────────────────────────────────────────
    if state == STATE_AGUARDANDO_TEXTO_ENTREGUE:
        await redis_queue.clear_state(tel)
        await redis_queue.clear_activity(tel)
        await redis_queue.reset_error(chat_id)
        await evolution_client.send_text_message(tel, _REPLY_JA_ENTREGUE)
        await _post_webhook_safe(
            _webhook(event_id, agendamento_id, tel, "JA_ENTREGUE", None, evolution_event, cid)
        )
        logger.info("on_response.ja_entregue_texto", agendamento_id=agendamento_id)
        return

    # ──────────────────────────────────────────────────────────────
    # Estado: aguardando escolha de período (após CONFIRMAR)
    # ──────────────────────────────────────────────────────────────
    if state.startswith(STATE_AGUARDANDO_PERIODO):
        ctx = _state_ctx(state, STATE_AGUARDANDO_PERIODO)
        data_iso = ctx.get("data")
        periodo = _classify_periodo(text)
        if periodo and data_iso:
            slot = slot_iso_de(data_iso, periodo)
            await redis_queue.clear_state(tel)
            await redis_queue.clear_activity(tel)
            await redis_queue.reset_error(chat_id)
            await evolution_client.send_text_message(
                tel,
                _REPLY_CONFIRMADO_TPL.format(
                    data_humana=_format_data_humana(data_iso),
                    periodo_humano=_PERIODO_LABEL[periodo],
                ),
            )
            await _post_webhook_safe(
                _webhook(event_id, agendamento_id, tel, "CONFIRMAR", slot, evolution_event, cid)
            )
            logger.info("on_response.confirmado", slot=slot, agendamento_id=agendamento_id)
            return
        await _handle_invalid(event_id, chat_id, tel, agendamento, agendamento_id, evolution_event, cid)
        return

    # ──────────────────────────────────────────────────────────────
    # Estado: aguardando escolha de data (após REMARCAR)
    # ──────────────────────────────────────────────────────────────
    if state.startswith(STATE_AGUARDANDO_DATA_REMARCAR):
        mapping = _state_ctx(state, STATE_AGUARDANDO_DATA_REMARCAR)
        data_iso = mapping.get(_normalize(text))
        if data_iso:
            await redis_queue.reset_error(chat_id)
            await redis_queue.set_state(
                tel, f"{STATE_AGUARDANDO_PERIODO_REMARCAR}{_json.dumps({'data': data_iso})}"
            )
            await redis_queue.track_activity(tel)
            await evolution_client.send_text_message(tel, build_periodo_text(data_iso))
            logger.info("on_response.data_remarcar_escolhida", data=data_iso, agendamento_id=agendamento_id)
            return
        await _handle_invalid(event_id, chat_id, tel, agendamento, agendamento_id, evolution_event, cid)
        return

    # ──────────────────────────────────────────────────────────────
    # Estado: aguardando período após escolher data (REMARCAR)
    # ──────────────────────────────────────────────────────────────
    if state.startswith(STATE_AGUARDANDO_PERIODO_REMARCAR):
        ctx = _state_ctx(state, STATE_AGUARDANDO_PERIODO_REMARCAR)
        data_iso = ctx.get("data")
        periodo = _classify_periodo(text)
        if periodo and data_iso:
            slot = slot_iso_de(data_iso, periodo)
            await redis_queue.clear_state(tel)
            await redis_queue.clear_activity(tel)
            await redis_queue.reset_error(chat_id)
            await evolution_client.send_text_message(
                tel,
                _REPLY_REMARCADO_TPL.format(
                    data_humana=_format_data_humana(data_iso),
                    periodo_humano=_PERIODO_LABEL[periodo],
                ),
            )
            await _post_webhook_safe(
                _webhook(event_id, agendamento_id, tel, "REMARCAR", slot, evolution_event, cid)
            )
            logger.info("on_response.remarcado", slot=slot, agendamento_id=agendamento_id)
            return
        await _handle_invalid(event_id, chat_id, tel, agendamento, agendamento_id, evolution_event, cid)
        return

    # ──────────────────────────────────────────────────────────────
    # Estado: AGUARDANDO_INICIAL (default após enviar_inicial)
    # ──────────────────────────────────────────────────────────────
    tipo = _classify_initial(text)
    if not tipo:
        await _handle_invalid(event_id, chat_id, tel, agendamento, agendamento_id, evolution_event, cid)
        return

    await redis_queue.reset_error(chat_id)

    if tipo == "CONFIRMAR":
        data_iso = (agendamento or {}).get("data", "")
        await redis_queue.set_state(
            tel, f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': data_iso})}"
        )
        await redis_queue.track_activity(tel)
        await evolution_client.send_text_message(tel, build_periodo_text(data_iso))
        logger.info("on_response.confirmar_pediu_periodo", agendamento_id=agendamento_id)

    elif tipo == "REMARCAR":
        texto_datas, mapping = build_datas_remarcar_text()
        await redis_queue.set_state(
            tel, f"{STATE_AGUARDANDO_DATA_REMARCAR}{_json.dumps(mapping)}"
        )
        await redis_queue.track_activity(tel)
        await evolution_client.send_text_message(tel, texto_datas)
        logger.info("on_response.remarcar_pediu_data", agendamento_id=agendamento_id)

    elif tipo == "JA_ENTREGUE":
        await redis_queue.set_state(tel, STATE_AGUARDANDO_TEXTO_ENTREGUE)
        await redis_queue.track_activity(tel)
        await evolution_client.send_text_message(tel, MSG_JA_ENTREGUE_PERGUNTA)
        logger.info("on_response.ja_entregue_pediu_texto", agendamento_id=agendamento_id)


# ---------------------------------------------------------------------------
# Erro / reenvio
# ---------------------------------------------------------------------------

async def _handle_invalid(event_id, chat_id, tel, agendamento, agendamento_id, evolution_event, cid):
    errors = await redis_queue.incr_error(chat_id)
    logger.info("on_response.invalid", errors=errors, agendamento_id=agendamento_id)
    await _post_webhook_safe(
        _webhook(event_id, agendamento_id, tel, "RESPOSTA_INVALIDA", None, evolution_event, cid)
    )

    if errors >= _MAX_ERRORS:
        await redis_queue.reset_error(chat_id)
        await redis_queue.clear_state(tel)
        await redis_queue.clear_activity(tel)
        await _post_webhook_safe(
            _webhook(None, agendamento_id, tel, "FALHA", None, None, cid)
        )
        logger.warning("on_response.max_errors_reached", agendamento_id=agendamento_id)
        return

    # Unifica fallback + reenvio do menu numa única mensagem (evita 2 envios em rajada)
    if agendamento is not None:
        _, texto = build_initial_text(agendamento)
        await evolution_client.send_text_message(tel, _FALLBACK_PREFIX + texto)
        await redis_queue.set_state(tel, STATE_INICIAL)
    else:
        await evolution_client.send_text_message(tel, _FALLBACK_PREFIX.rstrip())
