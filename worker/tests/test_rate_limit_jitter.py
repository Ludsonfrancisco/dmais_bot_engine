"""Tests for rate-limiting and jitter behaviour.

These tests validate the existing implementation without requiring a real Redis
server or Lua support in fakeredis.
"""

from unittest.mock import AsyncMock, patch

import pytest

from worker.evolution_client import (
    EvolutionClient,
    _ACQUIRE_SCRIPT,
    _BUCKET_KEY,
    _LAST_REFILL_KEY,
)
from worker.settings import settings


class FakeRedisEvalClient:
    """Small async fake for Redis.eval().

    EvolutionClient.acquire() loops until Redis eval returns 1.
    Any other value is interpreted as a wait time in seconds.
    """

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        if not self.results:
            raise AssertionError(
                "FakeRedisEvalClient received more eval calls than expected"
            )
        return self.results.pop(0)


class _BreakLoop(Exception):
    """Used to stop worker.main._poll_loop(), which is intentionally infinite."""


async def test_acquire_allows_configured_capacity_without_sleep():
    """The first 4 acquires should pass immediately when Redis returns tokens."""
    client = EvolutionClient()
    fake_redis = FakeRedisEvalClient([1] * settings.MAX_MESSAGES_PER_MINUTE)

    with (
        patch("worker.evolution_client.redis_queue") as mock_rq,
        patch(
            "worker.evolution_client.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_rq._ensure_client.return_value = fake_redis

        for _ in range(settings.MAX_MESSAGES_PER_MINUTE):
            await client.acquire()

    assert len(fake_redis.calls) == settings.MAX_MESSAGES_PER_MINUTE
    mock_sleep.assert_not_awaited()


async def test_acquire_waits_when_bucket_is_empty_then_retries():
    """When Redis returns a wait time, acquire() sleeps and retries."""
    client = EvolutionClient()
    fake_redis = FakeRedisEvalClient(["15.0", 1])

    with (
        patch("worker.evolution_client.redis_queue") as mock_rq,
        patch(
            "worker.evolution_client.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
    ):
        mock_rq._ensure_client.return_value = fake_redis

        await client.acquire()

    assert len(fake_redis.calls) == 2
    mock_sleep.assert_awaited_once_with(15.0)


async def test_acquire_uses_token_bucket_lua_parameters():
    """acquire() must call Redis eval with the configured token bucket parameters."""
    client = EvolutionClient()
    fake_redis = FakeRedisEvalClient([1])

    with patch("worker.evolution_client.redis_queue") as mock_rq:
        mock_rq._ensure_client.return_value = fake_redis

        await client.acquire()

    assert len(fake_redis.calls) == 1

    call = fake_redis.calls[0]
    script, num_keys, bucket_key, last_refill_key, capacity, refill_rate, now = call

    assert script == _ACQUIRE_SCRIPT
    assert num_keys == 2
    assert bucket_key == _BUCKET_KEY
    assert last_refill_key == _LAST_REFILL_KEY
    assert capacity == str(settings.MAX_MESSAGES_PER_MINUTE)
    assert float(refill_rate) == settings.MAX_MESSAGES_PER_MINUTE / 60.0
    assert float(now) > 0


def test_max_messages_per_minute_is_four():
    """Project safety requirement: WhatsApp anti-ban limit is 4 msg/min."""
    assert settings.MAX_MESSAGES_PER_MINUTE == 4


def test_poll_loop_source_contains_dispatch_jitter():
    """Static guard: dispatched messages must use random.uniform(8, 22)."""
    import inspect

    from worker.main import _poll_loop

    source = inspect.getsource(_poll_loop)

    assert "random.uniform(8, 22)" in source
    assert "await asyncio.sleep(random.uniform(8, 22))" in source


async def test_dispatched_message_uses_random_jitter_sleep():
    """When a message is dispatched, _poll_loop sleeps using random.uniform(8, 22)."""
    from worker.main import _poll_loop

    async def fake_listar_pendentes(page):
        assert page == 1
        return {
            "results": [
                {
                    "id": "ag-1",
                    "status": "PENDENTE_CONTATO",
                    "cliente_nome": "Cliente Teste",
                    "cliente_telefone": "+5511999999999",
                    "data_agendada": "2099-01-01",
                    "janela_horario": "MANHA",
                }
            ],
            "next": None,
        }

    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)
        # First sleep is dispatch jitter. Second is polling interval sleep.
        if len(sleep_calls) >= 2:
            raise _BreakLoop()

    with (
        patch("worker.main.django_client") as mock_django,
        patch(
            "worker.main.enviar_inicial.handle", new_callable=AsyncMock
        ) as mock_handle,
        patch(
            "worker.main.redis_queue.scan_timeouts", new_callable=AsyncMock
        ) as mock_scan,
        patch("worker.main.circuit_breaker.is_open", new_callable=AsyncMock) as mock_cb,
        patch("worker.main.random.uniform") as mock_uniform,
        patch("worker.main.asyncio.sleep", side_effect=fake_sleep),
    ):
        mock_django.listar_pendentes = fake_listar_pendentes
        mock_handle.return_value = "OK"
        mock_scan.return_value = []
        mock_cb.return_value = False
        mock_uniform.side_effect = [15.5, 0.0]

        with pytest.raises(_BreakLoop):
            await _poll_loop()

    mock_uniform.assert_any_call(8, 22)
    assert sleep_calls[0] == 15.5


async def test_skipped_message_does_not_use_dispatch_jitter_sleep():
    """If enviar_inicial returns SKIP, no per-message jitter should be applied."""
    from worker.main import _poll_loop

    async def fake_listar_pendentes(page):
        assert page == 1
        return {
            "results": [
                {
                    "id": "ag-1",
                    "status": "PENDENTE_CONTATO",
                    "cliente_nome": "Cliente Teste",
                    "cliente_telefone": "+5511999999999",
                    "data_agendada": "2099-01-01",
                    "janela_horario": "MANHA",
                }
            ],
            "next": None,
        }

    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)
        raise _BreakLoop()

    with (
        patch("worker.main.django_client") as mock_django,
        patch(
            "worker.main.enviar_inicial.handle", new_callable=AsyncMock
        ) as mock_handle,
        patch("worker.main.random.uniform") as mock_uniform,
        patch("worker.main.asyncio.sleep", side_effect=fake_sleep),
    ):
        mock_django.listar_pendentes = fake_listar_pendentes
        mock_handle.return_value = "SKIP"
        mock_uniform.return_value = 0.0

        with pytest.raises(_BreakLoop):
            await _poll_loop()

    # Only the polling interval jitter should run. The per-message (8, 22)
    # jitter must not run when the handler skipped sending.
    assert mock_uniform.call_count == 1
    assert mock_uniform.call_args.args != (8, 22)
    assert len(sleep_calls) == 1


def test_poll_loop_source_contains_polling_interval_jitter():
    """Static guard: polling sleep must include +/-20% jitter and a 1s floor."""
    import inspect

    from worker.main import _poll_loop

    source = inspect.getsource(_poll_loop)

    assert "random.uniform(-0.2 * interval, 0.2 * interval)" in source
    assert "max(1.0, interval + jitter)" in source


async def test_polling_interval_sleep_uses_plus_minus_twenty_percent_jitter():
    """The final sleep after each poll cycle uses +/-20% of POLLING_INTERVAL_SECONDS."""
    from worker.main import _poll_loop

    interval = settings.POLLING_INTERVAL_SECONDS
    expected_jitter = 0.2 * interval
    expected_sleep = interval + expected_jitter
    sleep_calls = []

    async def fake_listar_pendentes(page):
        assert page == 1
        return {"results": [], "next": None}

    async def fake_sleep(duration):
        sleep_calls.append(duration)
        raise _BreakLoop()

    with (
        patch("worker.main.django_client") as mock_django,
        patch("worker.main.random.uniform") as mock_uniform,
        patch("worker.main.asyncio.sleep", side_effect=fake_sleep),
    ):
        mock_django.listar_pendentes = fake_listar_pendentes
        mock_uniform.return_value = expected_jitter

        with pytest.raises(_BreakLoop):
            await _poll_loop()

    mock_uniform.assert_called_once_with(-0.2 * interval, 0.2 * interval)
    assert sleep_calls == [expected_sleep]


async def test_polling_interval_sleep_has_minimum_floor():
    """For very small intervals, polling sleep should be floored at 1.0s."""
    from worker.main import _poll_loop

    sleep_calls = []

    async def fake_listar_pendentes(page):
        assert page == 1
        return {"results": [], "next": None}

    async def fake_sleep(duration):
        sleep_calls.append(duration)
        raise _BreakLoop()

    with (
        patch("worker.main.django_client") as mock_django,
        patch("worker.main.settings") as mock_settings,
        patch("worker.main.random.uniform") as mock_uniform,
        patch("worker.main.asyncio.sleep", side_effect=fake_sleep),
    ):
        mock_django.listar_pendentes = fake_listar_pendentes
        mock_settings.POLLING_INTERVAL_SECONDS = 0.5
        mock_uniform.return_value = -0.1

        with pytest.raises(_BreakLoop):
            await _poll_loop()

    assert sleep_calls == [1.0]
