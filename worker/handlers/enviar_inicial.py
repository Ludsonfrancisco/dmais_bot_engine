"""
worker.handlers.enviar_inicial
===============================
Handler para envio da List Message inicial de confirmação de coleta.

Referência: PRD.md §4.1 — Fluxo principal (disparo inicial).

Funcionalidades planejadas:
    - async handle(agendamento: dict) -> None
    - Fluxo:
        1. Verifica was_sent(agendamento_id) no Redis → skip se já enviado.
        2. Monta payload via payloads.list_initial.build_initial_list().
        3. Chama evolution_client.send_list_message(payload).
        4. Marca sent:<agendamento_id> no Redis (TTL 24h).
    - Gera correlation_id único por agendamento.
    - Log estruturado de cada etapa.
"""

# TODO: Implementar na task 10.C.17
