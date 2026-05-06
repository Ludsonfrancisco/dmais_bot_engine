"""
dmais_bot_engine.worker
=======================
Pacote principal do motor de disparo WhatsApp.

Módulos:
    - settings: Carregamento e validação de variáveis de ambiente.
    - logs: Configuração de structlog com correlation_id.
    - api_client: Cliente HTTP para a API Django (tenacity + httpx).
    - evolution_client: Cliente HTTP para EvolutionAPI com rate limiting.
    - redis_queue: Filas, idempotência e controle de estado em Redis.
    - main: Orquestração FastAPI + polling loop.
"""
