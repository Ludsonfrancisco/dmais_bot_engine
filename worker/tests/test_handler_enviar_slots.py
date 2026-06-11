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
    
    with patch("worker.handlers.enviar_slots.django_client.listar_slots", new_callable=AsyncMock) as mock_listar, \
         patch("worker.handlers.enviar_slots.evolution_client.send_text_message", new_callable=AsyncMock) as mock_send_text, \
         patch("worker.handlers.enviar_slots.redis_queue.set_state", new_callable=AsyncMock):
        
        mock_listar.return_value = mock_slots
        
        await handle(agendamento_id, telefone)
        
        mock_listar.assert_called_once_with(agendamento_id)
        mock_send_text.assert_called_once()
        # Verify text message contains numbered options
        args, _ = mock_send_text.call_args
        assert args[0] == telefone  # phone number
        assert "1" in args[1]  # contains numbered option

@pytest.mark.asyncio
async def test_handle_enviar_slots_no_slots():
    agendamento_id = 123
    telefone = "5511999998888"
    
    with patch("worker.handlers.enviar_slots.django_client.listar_slots", new_callable=AsyncMock) as mock_listar, \
         patch("worker.handlers.enviar_slots.evolution_client.send_text_message", new_callable=AsyncMock) as mock_send_text, \
         patch("worker.handlers.enviar_slots.django_client.post_webhook", new_callable=AsyncMock) as mock_webhook, \
         patch("worker.handlers.enviar_slots.redis_queue.clear_state", new_callable=AsyncMock):
        
        mock_listar.return_value = []
        
        await handle(agendamento_id, telefone)
        
        mock_listar.assert_called_once_with(agendamento_id)
        mock_send_text.assert_called_once()
        assert "Não há horários disponíveis" in mock_send_text.call_args[0][1]
        
        mock_webhook.assert_called_once()
        webhook_payload = mock_webhook.call_args[0][0]
        assert webhook_payload["tipo"] == "FALHA"
        assert webhook_payload["agendamento_id"] == agendamento_id

@pytest.mark.asyncio
async def test_handle_enviar_slots_error_django():
    agendamento_id = 123
    telefone = "5511999998888"
    
    with patch("worker.handlers.enviar_slots.django_client.listar_slots", side_effect=Exception("Django Error")):
        # Current handler lets Django/API errors propagate to the caller.
        with pytest.raises(Exception, match="Django Error"):
            await handle(agendamento_id, telefone)