from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from worker.handlers import on_response
from worker.redis_queue import RedisQueue

_CHAT_ID = "5511999998888@s.whatsapp.net"
_TELEFONE = "5511999998888"
_AGENDAMENTO = {
    "agendamento_id": 123,
    "nome": "Fulano",
    "telefone": _TELEFONE,
    "data": "2026-05-08",
    "hora": "14:00",
    "status": "PENDENTE_CONFIRMACAO",
}


def _make_event(event_id: str, row_id: str | None = None) -> dict:
    msg = {}
    if row_id is not None:
        msg = {
            "listResponseMessage": {
                "singleSelectReply": {"selectedRowId": row_id}
            }
        }
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"id": event_id, "remoteJid": _CHAT_ID, "fromMe": False},
            "message": msg,
        },
    }


@pytest.fixture
async def fake_rq():
    rq = RedisQueue()
    rq._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    return rq


@pytest.fixture
def mock_django():
    m = MagicMock()
    m.post_webhook = AsyncMock()
    return m


@pytest.fixture
def mock_evolution():
    m = MagicMock()
    m.send_text_message = AsyncMock()
    m.send_list_message = AsyncMock(return_value={})
    return m


@pytest.fixture
def mock_slots():
    return AsyncMock()


@pytest.fixture(autouse=True)
def patch_all(fake_rq, mock_django, mock_evolution, mock_slots):
    with (
        patch.object(on_response, "redis_queue", fake_rq),
        patch.object(on_response, "django_client", mock_django),
        patch.object(on_response, "evolution_client", mock_evolution),
        patch.object(on_response.enviar_slots, "handle", mock_slots),
    ):
        yield


async def test_confirmar_posts_webhook_with_tipo_confirmar(mock_django):
    await on_response.handle(_make_event("evt-c1", "CONFIRMAR"))
    call_payload = mock_django.post_webhook.call_args[0][0]
    assert call_payload["tipo"] == "CONFIRMAR"
    assert call_payload["agendamento_id"] == 123


async def test_remarcar_calls_enviar_slots(mock_slots):
    await on_response.handle(_make_event("evt-r1", "REMARCAR"))
    mock_slots.assert_awaited_once_with(123, _TELEFONE)


async def test_ja_entregue_posts_webhook_with_tipo_ja_entregue(mock_django):
    await on_response.handle(_make_event("evt-j1", "JA_ENTREGUE"))
    call_payload = mock_django.post_webhook.call_args[0][0]
    assert call_payload["tipo"] == "JA_ENTREGUE"


async def test_slot_chosen_posts_webhook_with_correct_slot(mock_django):
    await on_response.handle(_make_event("evt-s1", "SLOT:2026-05-12T09:00:00-03:00"))
    call_payload = mock_django.post_webhook.call_args[0][0]
    assert call_payload["slot_escolhido"] == "2026-05-12T09:00:00-03:00"


async def test_three_invalid_responses_posts_falha(mock_django, mock_evolution):
    await on_response.handle(_make_event("evt-i1"))  # texto livre
    await on_response.handle(_make_event("evt-i2"))
    await on_response.handle(_make_event("evt-i3"))

    tipos = [c[0][0]["tipo"] for c in mock_django.post_webhook.call_args_list]
    assert "FALHA" in tipos
    # Primeiras 2 devem ter reenviado a lista
    assert mock_evolution.send_list_message.call_count == 2


async def test_duplicate_event_id_does_not_post_webhook_twice(mock_django):
    await on_response.handle(_make_event("evt-dup", "CONFIRMAR"))
    await on_response.handle(_make_event("evt-dup", "CONFIRMAR"))  # duplicata
    assert mock_django.post_webhook.call_count == 1
