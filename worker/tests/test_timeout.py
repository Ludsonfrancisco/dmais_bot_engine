import time as _time
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from worker.handlers import on_conversation_timeout, on_response
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
        "data": {
            "key": {"id": event_id, "remoteJid": _CHAT_ID, "fromMe": False},
            "message": msg,
        },
    }


@pytest.fixture
async def fake_rq():
    rq = RedisQueue()
    rq._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
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
        patch.object(on_conversation_timeout, "redis_queue", fake_rq),
        patch.object(on_conversation_timeout, "django_client", mock_django),
    ):
        yield


# ─────────────────────────────────────────────────────────────
# RedisQueue timeout tracking
# ─────────────────────────────────────────────────────────────


async def test_track_activity_sets_key_and_sorted_set(fake_rq):
    await fake_rq.track_activity(_TELEFONE)
    # Activity key exists
    val = await fake_rq._ensure_client().get(f"activity:{_TELEFONE}")
    assert val is not None
    # Sorted set entry exists
    score = await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE)
    assert score is not None
    assert score > _time.time()


async def test_track_activity_updates_existing_entry(fake_rq):
    await fake_rq.track_activity(_TELEFONE)
    old_score = await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE)
    await fake_rq.track_activity(_TELEFONE)
    new_score = await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE)
    assert new_score > old_score


async def test_clear_activity_removes_key_and_sorted_set(fake_rq):
    await fake_rq.track_activity(_TELEFONE)
    await fake_rq.clear_activity(_TELEFONE)
    assert await fake_rq._ensure_client().get(f"activity:{_TELEFONE}") is None
    assert await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE) is None


async def test_scan_timeouts_returns_expired_members(fake_rq):
    # Add a member with deadline in the past
    client = fake_rq._ensure_client()
    await client.zadd("timeout_watch", {_TELEFONE: _time.time() - 100})
    # Add a member with deadline in the future
    await client.zadd("timeout_watch", {"5511888887777": _time.time() + 10000})

    timed_out = await fake_rq.scan_timeouts()
    assert _TELEFONE in timed_out
    assert "5511888887777" not in timed_out


async def test_scan_timeouts_empty_when_none_expired(fake_rq):
    client = fake_rq._ensure_client()
    await client.zadd("timeout_watch", {"5511999991111": _time.time() + 10000})
    assert await fake_rq.scan_timeouts() == []


# ─────────────────────────────────────────────────────────────
# on_conversation_timeout handler
# ─────────────────────────────────────────────────────────────


async def test_timeout_mid_flow_posts_falha_and_clears(fake_rq, mock_django):
    # Simulate mid-flow state
    await fake_rq.set_state(
        _TELEFONE, f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': '2026-05-19'})}"
    )
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.track_activity(_TELEFONE)

    await on_conversation_timeout.handle(_TELEFONE)

    # Posted FALHA
    assert mock_django.post_webhook.called
    payload = mock_django.post_webhook.call_args[0][0]
    assert payload["tipo"] == "FALHA"
    assert payload["raw"]["motivo"] == "timeout_conversa"
    assert payload["agendamento_id"] == 123

    # State, agendamento, activity cleared
    assert await fake_rq.get_state(_TELEFONE) is None
    assert await fake_rq.get_agendamento(_TELEFONE) is None
    assert await fake_rq._ensure_client().get(f"activity:{_TELEFONE}") is None
    assert await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE) is None


async def test_timeout_initial_state_skips_falha(fake_rq, mock_django):
    # Initial state — user never responded
    await fake_rq.set_state(_TELEFONE, STATE_INICIAL)
    await fake_rq.track_activity(_TELEFONE)

    await on_conversation_timeout.handle(_TELEFONE)

    # Did NOT post FALHA
    mock_django.post_webhook.assert_not_called()

    # Activity cleared (so it won't keep scanning)
    assert await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE) is None

    # State remains (Django will re-present as PENDENTE_CONTATO)
    assert await fake_rq.get_state(_TELEFONE) == STATE_INICIAL


async def test_timeout_all_states_trigger_falha(fake_rq, mock_django):
    """Every non-initial state should post FALHA on timeout."""
    mid_flow_states = [
        f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': '2026-05-19'})}",
        f"{STATE_AGUARDANDO_DATA_REMARCAR}{_json.dumps({'1': '2026-05-20'})}",
        f"{STATE_AGUARDANDO_PERIODO_REMARCAR}{_json.dumps({'data': '2026-05-20'})}",
        STATE_AGUARDANDO_TEXTO_ENTREGUE,
    ]

    for state in mid_flow_states:
        mock_django.post_webhook.reset_mock()
        await fake_rq.set_state(_TELEFONE, state)
        await fake_rq.track_activity(_TELEFONE)

        await on_conversation_timeout.handle(_TELEFONE)

        payload = mock_django.post_webhook.call_args[0][0]
        assert payload["tipo"] == "FALHA", f"Expected FALHA for state {state[:30]}"

        # Cleanup for next iteration
        await fake_rq.clear_state(_TELEFONE)
        await fake_rq.clear_activity(_TELEFONE)


# ─────────────────────────────────────────────────────────────
# Integration: valid responses reset timeout
# ─────────────────────────────────────────────────────────────


async def test_confirmar_sets_activity_tracking(fake_rq):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(_TELEFONE, STATE_INICIAL)

    await on_response.handle(_event("evt-t1", "1"))

    # Activity should be tracked
    val = await fake_rq._ensure_client().get(f"activity:{_TELEFONE}")
    assert val is not None
    score = await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE)
    assert score is not None
    assert score > _time.time()


async def test_remarcar_sets_activity_tracking(fake_rq):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(_TELEFONE, STATE_INICIAL)

    await on_response.handle(_event("evt-t2", "2"))

    val = await fake_rq._ensure_client().get(f"activity:{_TELEFONE}")
    assert val is not None


async def test_ja_entregue_sets_activity_tracking(fake_rq):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(_TELEFONE, STATE_INICIAL)

    await on_response.handle(_event("evt-t3", "3"))

    val = await fake_rq._ensure_client().get(f"activity:{_TELEFONE}")
    assert val is not None


async def test_periodo_confirmation_clears_activity(
    fake_rq, mock_django, mock_evolution
):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(
        _TELEFONE, f"{STATE_AGUARDANDO_PERIODO}{_json.dumps({'data': '2026-05-19'})}"
    )
    await fake_rq.track_activity(_TELEFONE)

    await on_response.handle(_event("evt-p1", "1"))

    # After confirmation, activity should be cleared (conversation done)
    assert await fake_rq._ensure_client().get(f"activity:{_TELEFONE}") is None
    assert await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE) is None


async def test_remarcado_confirmation_clears_activity(fake_rq):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(
        _TELEFONE,
        f"{STATE_AGUARDANDO_PERIODO_REMARCAR}{_json.dumps({'data': '2026-05-20'})}",
    )
    await fake_rq.track_activity(_TELEFONE)

    await on_response.handle(_event("evt-pr1", "2"))

    assert await fake_rq._ensure_client().get(f"activity:{_TELEFONE}") is None
    assert await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE) is None


async def test_max_errors_clears_activity(fake_rq):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(_TELEFONE, STATE_INICIAL)
    await fake_rq.track_activity(_TELEFONE)

    # 3 invalid responses
    await on_response.handle(_event("evt-i1", "xyz"))
    await on_response.handle(_event("evt-i2", "abc"))
    await on_response.handle(_event("evt-i3", "qwe"))

    assert await fake_rq._ensure_client().get(f"activity:{_TELEFONE}") is None


async def test_ja_entregue_texto_clears_activity(fake_rq, mock_django, mock_evolution):
    await fake_rq.store_agendamento(_TELEFONE, _AGENDAMENTO)
    await fake_rq.set_state(_TELEFONE, STATE_AGUARDANDO_TEXTO_ENTREGUE)
    await fake_rq.track_activity(_TELEFONE)

    await on_response.handle(_event("evt-tx1", "Entreguei na loja Centro"))

    assert await fake_rq._ensure_client().get(f"activity:{_TELEFONE}") is None
    assert await fake_rq._ensure_client().zscore("timeout_watch", _TELEFONE) is None
