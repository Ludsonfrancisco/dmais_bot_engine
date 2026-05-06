# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dmais_bot_engine` is a WhatsApp message dispatch engine for DMais reverse logistics. It polls a Django API for pending collection schedules and sends interactive WhatsApp List Messages via EvolutionAPI (Baileys). The worker has no database of its own — all durable state lives in the external Django API; Redis is operational-only.

**Status:** Most `worker/` files are stubs with `# TODO: Implementar na task 10.C.x` markers. See `TASKS.md` for the full Sprint C checklist.

## Commands

All development is Docker-based. There is no local test runner yet.

```bash
make up           # docker compose up -d --build (start everything)
make down         # stop containers, preserve volumes
make restart      # restart only the worker (after code changes)
make logs         # tail all logs
make logs-worker  # tail worker logs only
make ps           # check container health status
make health       # curl worker /health endpoint
make shell-worker # bash inside worker container
make shell-redis  # redis-cli inside Redis container
make qrcode       # fetch WhatsApp pairing QR (Evolution must be up)
make test-send    # POST a fake schedule to /debug/test-send
make clean        # DESTRUCTIVE: removes all volumes including WhatsApp session
```

To run a single Python command inside the worker:
```bash
docker compose exec worker python -c "..."
```

## Architecture

Three Docker services in `docker-compose.yml`:

| Service | Image | Role |
|---|---|---|
| `evolution-api` | `atendai/evolution-api:latest` | WhatsApp gateway (Baileys), port 8080 |
| `redis` | `redis:7-alpine` | Queues, idempotency, rate limiting |
| `worker` | local build `./worker` | FastAPI + async polling loop, port 8000 |

```
Django API (external) ←→ worker (FastAPI + poller) ←→ EvolutionAPI ←→ WhatsApp
                                    ↑↓
                                  Redis
```

### Worker internals (`worker/`)

- **`main.py`** — FastAPI app + lifespan that starts the polling background task. Routes: `POST /webhook/evolution`, `GET /health`.
- **`settings.py`** — `pydantic-settings` `Settings` class; singleton `settings` imported everywhere.
- **`logs.py`** — `structlog` in JSON mode with `correlation_id` via `contextvars`. All operations bind a `correlation_id`.
- **`api_client.py`** — Async `httpx` client for Django. Methods: `listar_pendentes(page)`, `listar_slots(agendamento_id)`, `post_webhook(payload)`. Uses `tenacity` retry (exponential backoff, max 5, on HTTPError/5xx).
- **`evolution_client.py`** — Async `httpx` client for EvolutionAPI. Token bucket rate limiter stored in Redis (`ratelimit:bucket`, `ratelimit:last_refill`). `acquire()` blocks async until token available; `send_list_message(payload)` calls `acquire()` first.
- **`redis_queue.py`** — Idempotency (`evt:<id>` SET NX EX 86400), send tracking (`sent:<agendamento_id>`), error counters (`errors:<chat_id>`, limit 3).
- **`payloads/`** — Pure functions that build EvolutionAPI payload dicts. `list_initial.build_initial_list(agendamento)` → 3 options (CONFIRMAR / REMARCAR / JA_ENTREGUE). `list_horarios.build_horarios_list(agendamento, slots)` → up to 10 slots, `rowId = SLOT:<iso8601>`.
- **`handlers/`** — Async handlers orchestrating the above:
  - `enviar_inicial.handle(agendamento)` — checks `was_sent`, sends List Message, marks sent.
  - `enviar_slots.handle(agendamento_id, telefone)` — fetches slots, sends horários list; if no slots → posts FALHA to Django.
  - `on_response.handle(evolution_event)` — webhook handler; deduplicates, classifies rowId, routes to enviar_slots or posts to Django; after 3 invalid responses posts FALHA.
  - `on_timeout.handle(agendamento_id)` — called by poller for TIMEOUT state; posts FALHA to Django, clears Redis counters.

### Key operational rules

- **Idempotency:** Every webhook from Evolution is checked with `is_duplicate_event(event_id)` before processing.
- **Rate limit:** Token bucket capped at `MAX_MESSAGES_PER_MINUTE` (default 30). `evolution_client.acquire()` must be called before every send.
- **Error tolerance:** The polling loop must never die — all exceptions must be caught and logged.
- **Volume `dmais_evolution_instances`:** Stores the paired WhatsApp session. Never delete this volume; losing it requires re-pairing via QR code.

## Environment Variables

Copy `.env.example` to `.env` before starting. Key variables:

- `DJANGO_API_BASE_URL` + `DJANGO_API_TOKEN` — external Django API
- `EVOLUTION_API_KEY` + `EVOLUTION_INSTANCE_NAME` (default: `dmais`) — EvolutionAPI auth
- `EVOLUTION_API_URL` — internal URL (default: `http://evolution-api:8080`)
- `REDIS_URL` — default: `redis://redis:6379/0`
- `POLLING_INTERVAL_SECONDS` — default: `60`
- `MAX_MESSAGES_PER_MINUTE` — default: `30`
