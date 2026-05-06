"""
worker.handlers.enviar_slots
==============================
Handler para envio da List Message de horários disponíveis (remarcação).

Referência: PRD.md §4.2 — Fluxo reativo (quando REMARCAR é selecionado).

Funcionalidades planejadas:
    - async handle(agendamento_id: int, telefone: str) -> None
    - Fluxo:
        1. Chama api_client.listar_slots(agendamento_id) no Django.
        2. Se sem slots disponíveis → envia texto neutro + posta FALHA no Django.
        3. Monta payload via payloads.list_horarios.build_horarios_list().
        4. Chama evolution_client.send_list_message(payload).
    - Log estruturado com correlation_id.
"""

# TODO: Implementar na task 10.C.18
