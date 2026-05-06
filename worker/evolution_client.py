"""
worker.evolution_client
=======================
Cliente HTTP assíncrono para a EvolutionAPI com rate limiting integrado.

Referência: PRD.md §3.2 (EvolutionAPI), §6.1/6.2 (Payloads), §8 (Rate Limiting).

Funcionalidades planejadas:
    - httpx.AsyncClient para EvolutionAPI.
    - Header apikey: {EVOLUTION_API_KEY} em todas as chamadas.
    - Token bucket em Redis (30 msg/min configurável via MAX_MESSAGES_PER_MINUTE).
    - Método acquire() que aguarda assincronamente até haver token disponível.
    - Método send_list_message(payload: dict) -> dict
      POST {EVOLUTION_API_URL}/message/sendList/{EVOLUTION_INSTANCE_NAME}
    - Tratamento de erros e logging com correlation_id.

Rate Limiting (Token Bucket):
    - Capacidade = MAX_MESSAGES_PER_MINUTE (default 30).
    - Refill linear: 1 token a cada 60/MAX segundos.
    - Chaves Redis: ratelimit:bucket, ratelimit:last_refill.
    - acquire() bloqueia assincronamente se sem tokens.
"""

# TODO: Implementar na task 10.C.14
