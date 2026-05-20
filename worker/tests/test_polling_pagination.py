import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from worker import main
from worker.api_client import DjangoAPIClient
from worker.settings import settings


def _raw_agendamento(
    agendamento_id: str,
    status: str,
    *,
    nome: str = "Fulano",
    telefone: str = "+5511999998888",
    data_agendada: str = "2099-05-19T08:00:00-03:00",
    janela_horario: str = "MANHA",
) -> dict:
    return {
        "id": agendamento_id,
        "status": status,
        "cliente_nome": nome,
        "cliente_telefone": telefone,
        "data_agendada": data_agendada,
        "janela_horario": janela_horario,
    }


async def test_poll_loop_consumes_all_paginated_pendentes_and_routes_statuses():
    django_client = MagicMock()
    django_client.listar_pendentes = AsyncMock(
        side_effect=[
            {
                "results": [
                    _raw_agendamento(
                        "ag-1",
                        "PENDENTE_CONTATO",
                        nome="Cliente Um",
                        telefone="+5511111111111",
                    ),
                    _raw_agendamento("ag-timeout", "TIMEOUT"),
                ],
                "next": "https://test.example.com/api/logistica-reversa/pendentes-recolha/?page=2",
            },
            {
                "results": [
                    _raw_agendamento(
                        "ag-2",
                        "PENDENTE_CONTATO",
                        nome="Cliente Dois",
                        telefone="+5522222222222",
                        janela_horario="TARDE",
                    ),
                    _raw_agendamento("ag-ignored", "CONFIRMADO"),
                ],
                "next": "https://test.example.com/api/logistica-reversa/pendentes-recolha/?page=3",
            },
            {
                "results": [],
                "next": None,
            },
        ]
    )

    enviar_inicial = AsyncMock(return_value="SKIP")
    on_timeout = AsyncMock()

    # Encerra o while True depois que o ciclo completo termina e o poller
    # chega ao sleep entre ciclos. Como enviar_inicial retorna "SKIP", não há
    # sleep de jitter por mensagem neste teste.
    sleep = AsyncMock(side_effect=asyncio.CancelledError)

    with (
        patch.object(main, "django_client", django_client),
        patch.object(main.enviar_inicial, "handle", enviar_inicial),
        patch.object(main.on_timeout, "handle", on_timeout),
        patch.object(main.asyncio, "sleep", sleep),
    ):
        with pytest.raises(asyncio.CancelledError):
            await main._poll_loop()

    django_client.listar_pendentes.assert_has_awaits([call(1), call(2), call(3)])
    assert django_client.listar_pendentes.await_count == 3

    assert enviar_inicial.await_count == 2
    payloads = [await_call.args[0] for await_call in enviar_inicial.await_args_list]

    assert payloads[0] == {
        "agendamento_id": "ag-1",
        "nome": "Cliente Um",
        "telefone": "5511111111111",
        "data": "2099-05-19",
        "hora": "MANHA",
        "status": "PENDENTE_CONTATO",
    }
    assert payloads[1] == {
        "agendamento_id": "ag-2",
        "nome": "Cliente Dois",
        "telefone": "5522222222222",
        "data": "2099-05-19",
        "hora": "TARDE",
        "status": "PENDENTE_CONTATO",
    }

    on_timeout.assert_awaited_once_with("ag-timeout")


async def test_poll_loop_stops_pagination_when_next_is_missing():
    django_client = MagicMock()
    django_client.listar_pendentes = AsyncMock(
        return_value={
            "results": [],
            # "next" ausente de propósito: data.get("next") deve ser falsy.
        }
    )
    sleep = AsyncMock(side_effect=asyncio.CancelledError)

    with (
        patch.object(main, "django_client", django_client),
        patch.object(main.asyncio, "sleep", sleep),
    ):
        with pytest.raises(asyncio.CancelledError):
            await main._poll_loop()

    django_client.listar_pendentes.assert_awaited_once_with(1)


async def test_listar_pendentes_calls_django_endpoint_with_page_param():
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [], "next": None}

    class FakeHTTPClient:
        def __init__(self):
            self.calls = []

        async def get(self, url, *, params=None):
            self.calls.append((url, params))
            return FakeResponse()

    fake_http = FakeHTTPClient()
    client = DjangoAPIClient()
    client._client = fake_http

    response = await client.listar_pendentes(page=7)

    assert response == {"results": [], "next": None}
    assert fake_http.calls == [
        (
            f"{settings.DJANGO_API_BASE_URL}/api/logistica-reversa/pendentes-recolha/",
            {"page": 7},
        )
    ]
