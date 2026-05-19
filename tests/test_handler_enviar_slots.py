import pytest
from unittest.mock import AsyncMock, patch
from worker.handlers.enviar_slots import handle

@pytest.mark.asyncio
async def test_handle_enviar_slots_success():
    agendamento_id = 123
    telefone = "5511999998888"
    mock_slots = [
        {"inicio": "2026-05-12T09:00:00-03:00", "fim": "2026-05-12T11:00:00-03:00"}
    ]
    
    with patch("worker.handlers.enviar_slots.api_client.listar_slots", new_callable=AsyncMock) as mock_listar, \
         patch("worker.handlers.enviar_slots.evolution_client.send_list_message", new_callable=AsyncMock) as mock_send_list:
        
        mock_listar.return_value = mock_slots
        
        await handle(agendamento_id, telefone)
        
        mock_listar.assert_called_once_with(agendamento_id)
        mock_send_list.assert_called_once()
        # Verify payload contains the number
        args, _ = mock_send_list.call_args
        assert args[0]["number"] == telefone

@pytest.mark.asyncio
async def test_handle_enviar_slots_no_slots():
    agendamento_id = 123
    telefone = "5511999998888"
    
    with patch("worker.handlers.enviar_slots.api_client.listar_slots", new_callable=AsyncMock) as mock_listar, \
         patch("worker.handlers.enviar_slots.evolution_client.send_text_message", new_callable=AsyncMock) as mock_send_text, \
         patch("worker.handlers.enviar_slots.api_client.post_webhook", new_callable=AsyncMock) as mock_webhook:
        
        mock_listar.return_value = []
        
        await handle(agendamento_id, telefone)
        
        mock_listar.assert_called_once_with(agendamento_id)
        mock_send_text.assert_called_once()
        assert "não encontrei horários" in mock_send_text.call_args[0][1]
        
        mock_webhook.assert_called_once()
        webhook_payload = mock_webhook.call_args[0][0]
        assert webhook_payload["tipo"] == "FALHA"
        assert webhook_payload["agendamento_id"] == agendamento_id

@pytest.mark.asyncio
async def test_handle_enviar_slots_error_django():
    agendamento_id = 123
    telefone = "5511999998888"
    
    with patch("worker.handlers.enviar_slots.api_client.listar_slots", side_effect=Exception("Django Error")):
        # Should not raise exception (it's caught in the handler)
        await handle(agendamento_id, telefone)
