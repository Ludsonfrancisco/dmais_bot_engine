"""
worker.handlers.on_response
=============================
Handler para processamento de webhooks recebidos da EvolutionAPI.

Referência: PRD.md §4.2 — Fluxo reativo (recebimento de webhook).

Funcionalidades planejadas:
    - async handle(evolution_event: dict) -> None
    - Fluxo:
        1. Extrai event_id; verifica idempotência via is_duplicate_event().
        2. Classifica resposta:
            - List reply com rowId CONFIRMAR → posta no Django.
            - List reply com rowId REMARCAR → chama enviar_slots.handle().
            - List reply com rowId JA_ENTREGUE → posta no Django.
            - List reply com rowId SLOT:<iso8601> → extrai ISO, posta no Django.
            - Texto livre / opção desconhecida → incrementa erro:
                - < 3 erros: envia fallback + reenvia List inicial.
                - ≥ 3 erros: posta FALHA no Django e encerra conversa.
        3. Sempre posta evento canônico no Django via api_client.post_webhook().
    - Idempotência: SET evt:<event_id> NX EX 86400.
    - Log com correlation_id.
"""

# TODO: Implementar na task 10.C.19
