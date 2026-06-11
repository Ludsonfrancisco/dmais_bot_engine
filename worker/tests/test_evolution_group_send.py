from unittest.mock import AsyncMock, patch

import pytest

from worker.evolution_client import EvolutionClient


@pytest.mark.asyncio
async def test_send_group_text_message_uses_group_jid_without_check_exists():
    client = EvolutionClient()

    with (
        patch.object(
            client, "_send_text_with_circuit", new_callable=AsyncMock
        ) as mock_send,
        patch.object(
            client, "check_exists", new_callable=AsyncMock
        ) as mock_check_exists,
    ):
        mock_send.return_value = {"ok": True}

        result = await client.send_group_text_message(
            "120363000000000000@g.us", "Olá grupo"
        )

    mock_send.assert_called_once_with(
        "120363000000000000@g.us", "Olá grupo", log_field="group_jid"
    )
    mock_check_exists.assert_not_called()
    assert result == {"ok": True}
