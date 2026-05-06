"""
worker.api_client
=================
Cliente HTTP assíncrono para comunicação com a API Django externa.

Referência: PRD.md §4 — Fluxos, §6.3/6.4 — Payloads.

Funcionalidades planejadas:
    - httpx.AsyncClient reaproveitável (lifespan gerenciado pelo main.py).
    - Header Authorization: Token {DJANGO_API_TOKEN} em todas as chamadas.
    - Retry via tenacity (backoff exponencial, max 5, retry em HTTPError e 5xx).
    - Logging de cada chamada com correlation_id.

Métodos:
    - async listar_pendentes(page: int) -> dict
      GET /api/logistica-reversa/pendentes-recolha/?page={page}

    - async listar_slots(agendamento_id: int) -> list[dict]
      GET /api/logistica-reversa/slots/{agendamento_id}/

    - async post_webhook(payload: dict) -> None
      POST /api/logistica-reversa/whatsapp-webhook/
"""

# TODO: Implementar na task 10.C.11
