from unittest.mock import AsyncMock, patch

import pytest

from worker.reports.sender import send_report_text
from worker.settings import Settings


def _settings(**overrides) -> Settings:
    data = {
        "DJANGO_API_BASE_URL": "https://api.example.com",
        "DJANGO_API_TOKEN": "token",
        "EVOLUTION_API_KEY": "evo-key",
    }
    data.update(overrides)
    return Settings(**data)


@pytest.mark.asyncio
async def test_send_report_text_sends_to_test_group_with_test_prefix():
    config = _settings(
        REPORT_TARGETS="test", WHATSAPP_TEST_GROUP_JID="120363000000000000@g.us"
    )

    with patch(
        "worker.reports.sender.evolution_client.send_group_text_message",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = {"key": {"id": "abc"}}

        result = await send_report_text("Relatório de teste", config=config)

    mock_send.assert_called_once_with(
        "120363000000000000@g.us", "[AMBIENTE DE TESTE]\nRelatório de teste"
    )
    assert result[0]["target"] == "test"
    assert result[0]["group_jid"] == "1203***00@g.us"


@pytest.mark.asyncio
async def test_send_report_text_can_send_to_test_and_production_when_explicitly_configured():
    config = _settings(
        REPORT_TARGETS="test,production",
        WHATSAPP_TEST_GROUP_JID="120363000000000000@g.us",
        WHATSAPP_REPORT_GROUP_JID="120363111111111111@g.us",
    )

    with patch(
        "worker.reports.sender.evolution_client.send_group_text_message",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = {"ok": True}

        result = await send_report_text("Relatório aprovado", config=config)

    assert mock_send.call_args_list[0].args == (
        "120363000000000000@g.us",
        "[AMBIENTE DE TESTE]\nRelatório aprovado",
    )
    assert mock_send.call_args_list[1].args == (
        "120363111111111111@g.us",
        "Relatório aprovado",
    )
    assert [item["target"] for item in result] == ["test", "production"]
