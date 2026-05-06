"""
worker.handlers.on_timeout
============================
Handler para agendamentos que atingiram timeout (sinalizado pelo Django).

Referência: PRD.md §4.3 — Fluxo de timeout.

Funcionalidades planejadas:
    - async handle(agendamento_id: int) -> None
    - Acionado pelo polling quando o Django retorna status TIMEOUT.
    - Posta evento FALHA no Django via api_client.post_webhook().
    - Limpa contadores Redis (errors:<chat_id>, sent:<agendamento_id>).
    - Log com correlation_id.
"""

# TODO: Implementar na task 10.C.20
