"""
worker.main
============
Ponto de entrada do motor: FastAPI + polling loop em background.

Referência: PRD.md §4 (Fluxos), §9 (Endpoints).

Funcionalidades planejadas:
    - FastAPI(title="dmais_bot_engine")
    - Lifespan: inicia poller como asyncio.Task em background.
    - POST /webhook/evolution → on_response.handle
    - GET /health → healthcheck (Redis ping + Evolution GET).
    - Polling loop:
      while True → pagina pendentes → enviar_inicial por agendamento → sleep.
      Exceções tratadas para nunca matar o loop.
    - Shutdown graceful: fecha httpx clients e redis.

Uso (via Docker):
    uvicorn worker.main:app --host 0.0.0.0 --port 8000
"""

# TODO: Implementar na task 10.C.21 + 10.C.24
