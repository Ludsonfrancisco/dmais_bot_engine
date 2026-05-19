import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from worker.handlers import on_response
from worker.handlers.enviar_inicial import STATE_INICIAL
from worker.handlers.on_response import (
    STATE_AGUARDANDO_DATA_REMARCAR,
    STATE_AGUARDANDO_PERIODO,
    STATE_AGUARDANDO_PERIODO_REMARCAR,
    STATE_AGUARDANDO_TEXTO_ENTREGUE,
)
from worker.redis_queue import RedisQueue

_CHAT_ID = "5511999998888@s.whatsapp.net"
_TELEFONE = "5511999998888"
_AGENDAMENTO = {
    "agendamento_id": 123,
    "nome": "Fulano",
    "telefone": _TELEFONE,
    "data": "2026-05-19",
    "hora": "14:00",
    "status": "PENDENTE_CONFIRMACAO",
}


def _event(event_id: str, text: str | None = None) -> dict:
    msg = {"conversation": text} if text is not None else {}
    return {
        "event": "messages.upsert",
        "data": {"key": {"id": event_id, "remoteJid": _CHAT_ID, "fromMe": False}, "message": msg},
    }


@pytest.fixture
async def fake_rq():
    rq = RedisQueue()
    rq._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await rq.set_state(_TELEFONE, STATE_INICIAL)
    return rq


@pytest.fixture
def mock_django():
    m = MagicMock()
    m.post_webhook = AsyncMock()
    return m


@pytest.fixture
def mock_evolution():
    m = MagicMock()
    m.send_text_message = AsyncMock(return_value={})
    return m


@pytest.fixture(autouse=True)
def patch_all(fake_rq, mock_django, mock_evolution):
    with (
        patch.object(on_response, "redis_queue", fake_rq),
        patch.object(on_response, "django_client", mock_django),
        patch.object(on_response, "evolution_client", mock_evolution),
    ):
        yield


# ─────────────────────────────────────────────────────────────
# Estado inicial → pergunta de período / lista de datas / pergunta texto
# ─────────────────────────────────────────────────────────────

async def test_confirmar_pede_periodo_e_atualiza_estado(fake_rq, mock_evolution, mock_django):
    await on_response.handle(_event("evt-c1", "1"))
    # Não posta webhook ainda — apenas pediu período
    mock_django.post_webhook.assert_not_called()
    # Mensagem pedindo período
    reply = mock_evolution.send_text_message.call_args[0][1]
    assert "período" in reply.lower()
    assert "Manhã" in reply and "Tarde" in reply
    # Estado atualizado
    new_state = await fake_rq.get_state(_TELEFONE)
    assert new_state.startswith(STATE_AGUARDANDO_PERIODO)
    assert _json.loads(new_state[len(STATE_AGUARDANDO_PERIODO):])["data"] == "2026-05-19"


async def test_remarcar_envia_lista_de_datas(fake_rq, mock_evolution, mock_django):
    await on_response.handle(_event("evt-r1", "2"))
    mock_django.post_webhook.assert_not_called()
    reply = mock_evolution.send_text_message.call_args[0][1]
    assert "1 — " in reply and "2 — " in reply and "3 — " in reply
    new_state = await fake_rq.get_state(_TELEFONE)
    assert new_state.startswith(STATE_AGUARDANDO_DATA_REMARCAR)


async def test_ja_entreguei_pede_texto_livre(fake_rq, mock_evolution, mock_django):
    await on_response.handle(_event("evt-j1", "3"))
    mock_django.post_webhook.assert_not_called()
    reply = mock_evolution.send_text_message.call_args[0][1]
    assert "onde" in reply.lower() and "quem" in reply.lower() and "quando" in reply.lower()
    assert await fake_rq.get_state(_TELEFONE) == STATE_AGUARDANDO_TEXTO_ENTREGUE


async def test_keywords_funcionam(fake_rq):
    await on_response.handle(_event("evt-kw1", "confirmar"))
    assert (await fake_rq.get_state(_TELEFONE)).startswith(STATE_AGUARDANDO_PERIODO)


# ─────────────────────────────────────────────────────────────
# Estado AGUARDANDO_PERIODO → confirma slot + posta webhook CONFIRMAR
# ─────────────────────────────────────────────────────────────

async def test_periodo_manha_confirma_e_posta_webhook(fake_rq, mock_django, mock_evolution):
    await fake_rq.set_state(_TELEFONE, f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': '2026-05-19'})}")
    await on_response.handle(_event("evt-p1", "1"))
    payload = mock_django.post_webhook.call_args[0][0]
    assert payload["tipo"] == "CONFIRMAR"
    assert payload["slot_escolhido"] == "2026-05-19T08:00:00-03:00"
    reply = mock_evolution.send_text_message.call_args[0][1]
    assert "AT3" in reply
    assert "confirmação" in reply.lower()
    assert "manhã" in reply.lower()
    assert await fake_rq.get_state(_TELEFONE) is None


async def test_periodo_tarde_grava_slot_12h(fake_rq, mock_django):
    await fake_rq.set_state(_TELEFONE, f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': '2026-05-19'})}")
    await on_response.handle(_event("evt-p2", "2"))
    assert mock_django.post_webhook.call_args[0][0]["slot_escolhido"] == "2026-05-19T12:00:00-03:00"


async def test_keyword_manha_funciona_no_periodo(fake_rq, mock_django):
    await fake_rq.set_state(_TELEFONE, f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': '2026-05-19'})}")
    await on_response.handle(_event("evt-p3", "manhã"))
    assert mock_django.post_webhook.call_args[0][0]["tipo"] == "CONFIRMAR"


# ─────────────────────────────────────────────────────────────
# Estado AGUARDANDO_DATA_REMARCAR → escolha data → vai pra período
# ─────────────────────────────────────────────────────────────

async def test_escolher_data_remarcar_pede_periodo(fake_rq, mock_evolution, mock_django):
    mapping = {"1": "2026-05-20", "2": "2026-05-21"}
    await fake_rq.set_state(_TELEFONE, f"{STATE_AGUARDANDO_DATA_REMARCAR}{_json.dumps(mapping)}")
    await on_response.handle(_event("evt-dr1", "1"))
    mock_django.post_webhook.assert_not_called()  # ainda não posta
    new_state = await fake_rq.get_state(_TELEFONE)
    assert new_state.startswith(STATE_AGUARDANDO_PERIODO_REMARCAR)
    assert _json.loads(new_state[len(STATE_AGUARDANDO_PERIODO_REMARCAR):])["data"] == "2026-05-20"


async def test_data_invalida_no_remarcar_incrementa_erro(fake_rq, mock_django):
    mapping = {"1": "2026-05-20"}
    await fake_rq.set_state(_TELEFONE, f"{STATE_AGUARDANDO_DATA_REMARCAR}{_json.dumps(mapping)}")
    await on_response.handle(_event("evt-dr-bad", "99"))
    assert mock_django.post_webhook.call_args[0][0]["tipo"] == "RESPOSTA_INVALIDA"


# ─────────────────────────────────────────────────────────────
# Estado AGUARDANDO_PERIODO_REMARCAR → REMARCAR + slot
# ─────────────────────────────────────────────────────────────

async def test_periodo_remarcar_posta_webhook_remarcar(fake_rq, mock_django, mock_evolution):
    await fake_rq.set_state(_TELEFONE, f"{STATE_AGUARDANDO_PERIODO_REMARCAR}{_json.dumps({'data': '2026-05-20'})}")
    await on_response.handle(_event("evt-pr1", "2"))
    payload = mock_django.post_webhook.call_args[0][0]
    assert payload["tipo"] == "REMARCAR"
    assert payload["slot_escolhido"] == "2026-05-20T12:00:00-03:00"
    reply = mock_evolution.send_text_message.call_args[0][1]
    assert "remarcada" in reply.lower()


# ─────────────────────────────────────────────────────────────
# Estado AGUARDANDO_TEXTO_ENTREGUE → posta webhook JA_ENTREGUE com qualquer texto
# ─────────────────────────────────────────────────────────────

async def test_texto_livre_apos_ja_entregue_posta_webhook(fake_rq, mock_django, mock_evolution):
    await fake_rq.set_state(_TELEFONE, STATE_AGUARDANDO_TEXTO_ENTREGUE)
    await on_response.handle(_event("evt-tx1", "Entreguei na loja Centro ao Joao na sexta passada"))
    payload = mock_django.post_webhook.call_args[0][0]
    assert payload["tipo"] == "JA_ENTREGUE"
    # texto livre fica no raw para o Django ler
    raw_text = payload["raw"]["data"]["message"]["conversation"]
    assert "Centro" in raw_text and "Joao" in raw_text
    reply = mock_evolution.send_text_message.call_args[0][1]
    assert "AT3" in reply
    assert "agradece" in reply.lower()
    assert await fake_rq.get_state(_TELEFONE) is None


# ─────────────────────────────────────────────────────────────
# Casos transversais
# ─────────────────────────────────────────────────────────────

async def test_extended_text_message_e_aceito(mock_django):
    evt = {
        "event": "messages.upsert",
        "data": {
            "key": {"id": "evt-ext", "remoteJid": _CHAT_ID, "fromMe": False},
            "message": {"extendedTextMessage": {"text": "1"}},
        },
    }
    await on_response.handle(evt)
    # Inicial: '1' = CONFIRMAR → pediu período (sem post ainda)
    mock_django.post_webhook.assert_not_called()


async def test_tres_respostas_invalidas_postam_falha(mock_django):
    await on_response.handle(_event("evt-i1", "xyz"))
    await on_response.handle(_event("evt-i2", "abc"))
    await on_response.handle(_event("evt-i3", "qwe"))
    tipos = [c[0][0]["tipo"] for c in mock_django.post_webhook.call_args_list]
    assert "FALHA" in tipos


async def test_duplicate_event_id_nao_processa_duas_vezes(fake_rq, mock_evolution):
    await on_response.handle(_event("evt-dup", "1"))
    await on_response.handle(_event("evt-dup", "1"))
    # Só uma mensagem de pergunta de período enviada
    assert mock_evolution.send_text_message.call_count == 1


async def test_chat_id_lid_usa_remote_jid_alt(fake_rq):
    """WhatsApp Multi-Device anonimiza remoteJid como @lid; deve ler remoteJidAlt."""
    evt = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": "evt-lid",
                "remoteJid": "256213623291991@lid",
                "remoteJidAlt": _CHAT_ID,
                "fromMe": False,
            },
            "message": {"conversation": "1"},
        },
    }
    await on_response.handle(evt)
    # estado mudou pra AGUARDANDO_PERIODO → confirma que reconheceu o agendamento
    new_state = await fake_rq.get_state(_TELEFONE)
    assert new_state.startswith(STATE_AGUARDANDO_PERIODO)


async def test_mensagem_sem_texto_e_ignorada(mock_django):
    evt = {
        "event": "messages.upsert",
        "data": {"key": {"id": "evt-empty", "remoteJid": _CHAT_ID, "fromMe": False}, "message": {}},
    }
    await on_response.handle(evt)
    mock_django.post_webhook.assert_not_called()


async def test_resposta_valida_reseta_contador_de_erros(fake_rq):
    await on_response.handle(_event("evt-i1", "xyz"))   # erro 1
    await on_response.handle(_event("evt-i2", "1"))     # válida — reseta
    assert await fake_rq._ensure_client().get(f"errors:{_CHAT_ID}") is None
