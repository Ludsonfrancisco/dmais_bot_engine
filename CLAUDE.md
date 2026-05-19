# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dmais_bot_engine` is a WhatsApp message dispatch engine for DMais reverse logistics (AT3 Internet). It polls a Django API (`dmais_portal`) for pending collection schedules and runs a conversational state machine in **plain text** over WhatsApp via EvolutionAPI (Baileys). The worker has no database of its own — all durable state lives in the external Django API; Redis is operational-only.

**Status:** End-to-end functional with 29 real customers tested. Bot disparates, customers reply, kanban transitions, audit trail captured.

## Important architectural shift (May 2026)

The original PRD specified WhatsApp **List Messages** (interactive menus). **This no longer works** — Meta deprecated interactive buttons/lists in the WhatsApp Web/Multi-Device protocol. Baileys (which Evolution uses) cannot send them reliably. The bot now uses **plain text with numbered options** and a multi-step state machine. See [`worker/handlers/on_response.py`](worker/handlers/on_response.py) for the state machine and [`worker/payloads/list_initial.py`](worker/payloads/list_initial.py) for message templates (filenames kept for historical reasons; content is plain text).

## Commands

All development is Docker-based.

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
make test         # run pytest inside worker container
make demo         # up + wait healthy + test-send + tail logs
make clean        # DESTRUCTIVE: removes all volumes including WhatsApp session and Postgres
```

On Windows, `make` may not be available — run `docker compose` commands directly. To run pytest inside the container:

```bash
docker compose exec worker bash -lc "cd /app/worker && python -m pytest tests/ -v"
```

Tests use `pytest-asyncio` (`asyncio_mode=auto`) and `fakeredis`. 43 unit tests covering payloads, on_response state machine (LID handling, lock, all flows), redis_queue, logs, settings.

## Architecture

Four Docker services in `docker-compose.yml`:

| Service | Image | Role |
|---|---|---|
| `evolution-api` | `evoapicloud/evolution-api:v2.3.5` (pinned) | WhatsApp gateway (Baileys), port 8080 |
| `postgres` | `postgres:16-alpine` | Required by Evolution v2 |
| `redis` | `redis:7-alpine` | Queues, idempotency, rate limiting, conversation state |
| `worker` | local build `./worker` | FastAPI + async polling loop, port 8000 |

```
Django API (dmais_portal) ←→ worker (FastAPI + poller) ←→ EvolutionAPI ←→ WhatsApp
                                    ↑↓                       ↓
                                  Redis                   Postgres
```

### Worker internals (`worker/`)

- **`main.py`** — FastAPI app + lifespan that starts the polling background task.
  - Routes: `POST /webhook/evolution`, `GET /health`, `POST /debug/test-send`
  - `_adapt()` converts Django shape (`cliente_nome`, `data_agendada`, UUID `id`) to worker shape (`nome`, `data`, `agendamento_id`). **Also auto-bumps `data_agendada` to tomorrow if it's in the past** (handles outdated spreadsheets).
  - Poller iterates `pendentes-recolha`, applies random sleep 8–22s between sends (jitter avoids fixed cadence pattern that triggers WhatsApp anti-spam).

- **`settings.py`** — `pydantic-settings` `Settings` class; singleton `settings` imported everywhere.

- **`logs.py`** — `structlog` in JSON mode with `correlation_id` via `contextvars`. All operations bind a `correlation_id`.

- **`api_client.py`** — Async `httpx` client for Django.
  - `listar_pendentes(page)` — polling endpoint.
  - `listar_slots(agendamento_id)` — slots endpoint (currently bypassed; date list is hardcoded for now).
  - `post_webhook(payload)` — POSTs `/whatsapp-webhook/` after a customer reply triggers a state transition.
  - `update_status(agendamento_id, status, inc_tentativas=False)` — PATCHes `/agendamentos/<id>/status/` to move kanban (PENDENTE_CONTATO → AGUARDANDO_CLIENTE) and increment `tentativas_envio`.

- **`evolution_client.py`** — Async `httpx` client for EvolutionAPI.
  - Token bucket rate limiter stored in Redis (`ratelimit:bucket`, `ratelimit:last_refill`). `acquire()` blocks async until token available.
  - `send_text_message(telefone, text)` — only sender used (List Message and Buttons are dead, see above).
  - `check_exists(telefone)` — pre-flight check via `/chat/whatsappNumbers/` to avoid 400s on numbers that aren't on WhatsApp.

- **`redis_queue.py`** — Redis-backed operational state.
  - Idempotency (`evt:<id>` SET NX EX 86400)
  - Send tracking (`sent:<agendamento_id>`)
  - Error counters (`errors:<chat_id>`, limit 3)
  - **State machine** (`state:<telefone>`): one of:
    - `AGUARDANDO_INICIAL` — waiting for 1/2/3 reply
    - `AGUARDANDO_PERIODO:{"data":"YYYY-MM-DD"}` — after CONFIRMAR, waiting for morning/afternoon
    - `AGUARDANDO_DATA_REMARCAR:{"1":"...","2":"...","3":"..."}` — after REMARCAR, waiting for date pick
    - `AGUARDANDO_PERIODO_REMARCAR:{"data":"YYYY-MM-DD"}` — after date pick, waiting for period
    - `AGUARDANDO_TEXTO_ENTREGUE` — after JA_ENTREGUE, waiting for free-text "where/whom/when"
  - Agendamento cache (`agendamento:<telefone>`, `agendamento_id:<id>`)

- **`payloads/list_initial.py`** — Message text builders. Despite the filename, all functions produce plain text strings, not List Message payloads.
  - `build_initial_text(agendamento)` → AT3-branded greeting with 3 options.
  - `build_periodo_text(data_str)` → period picker (1=Manhã, 2=Tarde).
  - `build_datas_remarcar_text()` → list of 3 hardcoded dates (SLOTS_DEMO).
  - `slot_iso_de(data, periodo)` → combines into ISO 8601 (MANHA=08:00, TARDE=12:00, -03:00).
  - `MSG_JA_ENTREGUE_PERGUNTA` — free-text prompt for "where/whom/when".

- **`payloads/list_horarios.py`** — Legacy slot list builder (preserved for compatibility with `enviar_slots` handler — not currently used in the new state machine flow).

- **`handlers/`**:
  - `enviar_inicial.handle(agendamento)` — Pre-checks `check_exists` (skips with FALHA + mark_sent if number doesn't exist on WhatsApp), sends initial AT3 text, sets state, **also PATCHes Django to move PENDENTE_CONTATO → AGUARDANDO_CLIENTE and increments `tentativas_envio`**. Returns `"SKIP"` if already sent (poller uses this to skip jitter delay).
  - `on_response.handle(evt)` — Full state machine. Per-chat `asyncio.Lock` serializes burst messages from the same client. Handles `@lid` JIDs via `remoteJidAlt` fallback. Filters out `@g.us`, `@newsletter`, `@broadcast`.
  - `enviar_slots.handle(agendamento_id, telefone)` — Legacy handler (not on the critical path now).
  - `on_timeout.handle(agendamento_id)` — Called by poller for TIMEOUT status.

### Conversation state machine

```
                     ┌─────────────────┐
   PENDENTE_CONTATO  │ enviar_inicial  │   tentativas++
   ──────────────────►  → send AT3     │  ─────────────►   AGUARDANDO_CLIENTE
                     │  → STATE_INICIAL│   (Django kanban)
                     └────────┬────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │"1" / "confirmar"    │"2" / "remarcar"     │"3" / "entreguei"
        ▼                     ▼                     ▼
   AGUARDANDO_PERIODO    AGUARDANDO_DATA_REMARCAR   AGUARDANDO_TEXTO_ENTREGUE
   {data}                {mapping idx→ISO}          (no ctx)
        │                     │                     │
        │"1"/"2"              │"1".."3" (date)      │free text
        │ MANHA/TARDE         ▼                     ▼
        │                AGUARDANDO_PERIODO_REMARCAR  Post webhook
        │                {data picked}              tipo=JA_ENTREGUE
        │                     │                     raw=<text>
        │                     │"1"/"2"              ▼
        │                     │ MANHA/TARDE         CONFIRMADO ✗→ JA_ENTREGUE
        ▼                     ▼
   Post webhook          Post webhook
   tipo=CONFIRMAR        tipo=REMARCAR
   slot=ISO              slot=ISO
        │                     │
        ▼                     ▼
   AGUARDANDO_CLIENTE    AGUARDANDO_CLIENTE
   → CONFIRMADO          → REMARCADO
   (Django state machine)
```

### Key operational rules

- **Idempotency:** Every webhook from Evolution checked via `is_duplicate_event(event_id)` before processing.
- **Per-chat serialization:** `asyncio.Lock` per `chat_id` in `on_response.py` prevents race conditions when a client sends multiple messages in rapid succession.
- **`@lid` (Linked ID) handling:** WhatsApp Multi-Device anonymizes some sender JIDs as `<random>@lid`. The real `@s.whatsapp.net` is in `remoteJidAlt`. `_chat_id()` prioritizes the alt when present.
- **Group/newsletter filter:** Messages from `@g.us`, `@newsletter`, `@broadcast` are silently ignored (the bot's WhatsApp account may be in groups).
- **Rate limit:** Token bucket capped at `MAX_MESSAGES_PER_MINUTE` (default 4, was 30). `evolution_client.acquire()` called before every send.
- **Jitter on dispatch:** Poller sleeps `random.uniform(8, 22)` seconds between dispatches to avoid fixed cadence pattern. Skipped agendamentos (`was_sent`) don't burn jitter.
- **Error tolerance:** The polling loop must never die — all exceptions caught and logged. Django webhook calls use `_post_webhook_safe` wrapper that absorbs failures so client reply isn't blocked.
- **Past-date handling:** If `agendamento.data_agendada` is before today, `_adapt()` bumps it to `today + 1` so the message doesn't say "agendada para [past date]".
- **Volume `dmais_evolution_instances`:** Stores the paired WhatsApp session. Never delete this volume; losing it requires re-pairing via QR code.

### Evolution version pin (do not bump casually)

The `evolution-api` image is pinned to **`v2.3.5`** (not `latest`). Newer versions break `sendList` ([#2390](https://github.com/EvolutionAPI/evolution-api/issues/2390)), though that's moot now since we don't use list messages anymore.

These env vars on the `evolution-api` service mitigate the pre-key timeout bug ([#2437](https://github.com/EvolutionAPI/evolution-api/issues/2437)):

```
CACHE_REDIS_ENABLED=false
CACHE_LOCAL_ENABLED=true
DATABASE_SAVE_DATA_CHATS=false
DATABASE_SAVE_DATA_CONTACTS=false
DATABASE_SAVE_DATA_HISTORIC=false
DATABASE_SAVE_DATA_LABELS=false
CONFIG_SESSION_PHONE_VERSION=2.3000.1033773198
```

Side effect: `Message` rows in Postgres stay `PENDING` even after delivery — verify delivery in the WhatsApp app, not the DB.

## Django side (dmais_portal)

The companion project at `../dmais_portal/` (Django 5.2) hosts the kanban UI and REST API. Key endpoints consumed by the worker:

- `GET /api/logistica-reversa/pendentes-recolha/` — agendamentos with `status='PENDENTE_CONTATO'`.
- `POST /api/logistica-reversa/whatsapp-webhook/` — receives `{event_id, agendamento_id, telefone, tipo, slot_escolhido, raw, correlation_id}` from the bot when a customer completes a flow step. Handler in `dmais_portal/logistica_reversa/api/views.py::WhatsAppWebhookView` auto-transitions PENDENTE_CONTATO → AGUARDANDO_CLIENTE before applying the final transition.
- `PATCH /api/logistica-reversa/agendamentos/<uuid>/status/` — direct status transition with optional `inc_tentativas` flag.

DRF authentication: **TokenAuthentication + SessionAuthentication** (added so the kanban page JS can use the session cookie instead of needing the bot's token). The bot uses Token; the browser uses Session.

To run the Django side locally on port 8001 (with `host.docker.internal` accessible from the worker container):

```powershell
$env:LR_DASHBOARD_TOKEN = "<token>"  # used in the kanban meta tag
cd ..\dmais_portal
.\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001 --noreload
```

`ALLOWED_HOSTS` must include `host.docker.internal` (already set in `dmais_portal/core/settings.py`).

## Environment Variables

Copy `.env.example` to `.env` before starting. Key variables:

- `DJANGO_API_BASE_URL` + `DJANGO_API_TOKEN` — external Django API. Use `http://host.docker.internal:8001` when Django runs on Windows host.
- `EVOLUTION_API_KEY` + `EVOLUTION_INSTANCE_NAME` (default: `dmais`) — EvolutionAPI auth
- `EVOLUTION_API_URL` — internal URL (default: `http://evolution-api:8080`)
- `REDIS_URL` — default: `redis://redis:6379/0`
- `POLLING_INTERVAL_SECONDS` — default: `60`
- `MAX_MESSAGES_PER_MINUTE` — default: `4` (was `30`; lowered to match business rule of 4/min anti-block)
- `LOG_LEVEL` — default: `INFO`
- `WORKER_HTTP_PORT` — default: `8000`

## ⚠️ Retomar o projeto em outra máquina / após reboot

Antes de subir a stack, leia o checklist abaixo. Há **5 pontos** que não vivem no Git e podem causar bloqueios silenciosos.

### Checklist de retomada

| # | Item | Verificar / Ação |
|---|---|---|
| 1 | **Pull do repo `dmais_bot_engine`** | `git pull origin main` — código e docs estão versionados |
| 2 | **Pull do repo `dmais_portal`** (irmão, `../dmais_portal`) | `git pull` — **o usuário é quem commita ali; nunca commite no portal sem permissão dele**. Verificar com ele se há mudanças não-pushadas: `core/settings.py`, `logistica_reversa/api/views.py`, `logistica_reversa/api/serializers.py`, `logistica_reversa/static/logistica_reversa/js/kanban.js` |
| 3 | **`.env` do bot_engine** | Gitignored. Copiar de outro lugar ou regenerar: `cp .env.example .env` e preencher `DJANGO_API_TOKEN`, `EVOLUTION_API_KEY`. O token do Django se gera com `python manage.py criar_token_motor --label <nome>` no dmais_portal. |
| 4 | **Sessão WhatsApp pareada** | Vive no volume Docker `dmais_evolution_instances` (local). Em nova máquina é necessário re-parear: `curl -X POST http://localhost:8080/instance/create ...` + escanear QR. **Backup recomendado** se for migração planejada (ver "Backup de volumes" no README). |
| 5 | **Redis state** | Volátil. Estados intermediários de conversas (período/data em andamento) se perdem — clientes precisam responder novamente do menu inicial. Os agendamentos pendentes continuam em `PENDENTE_CONTATO` no Django, e o polling reenviará. |

### Erros típicos e diagnóstico rápido

| Sintoma | Causa provável | Como verificar |
|---|---|---|
| Webhook do bot retorna 501 | `dmais_portal` sem a `WhatsAppWebhookView` implementada (versão antiga do código) | `curl -X POST -H 'Authorization: Token <token>' http://localhost:8001/api/logistica-reversa/whatsapp-webhook/ -d '{}'` deve retornar 400, não 501 |
| Cards do kanban abrem em branco | `lr_dashboard_token` vazio + `SessionAuthentication` ausente em DRF | `<meta name="lr-dashboard-token">` no HTML do kanban deve ter content; e `core/settings.py` deve ter `SessionAuthentication` nos `DEFAULT_AUTHENTICATION_CLASSES` |
| Worker dá 400 em `sendText` | Número não existe no WhatsApp (problema do "nono dígito" BR) | Pré-flight `check_exists` já cuida; veja log `enviar_inicial.number_not_on_whatsapp` |
| Worker em loop "agendamento_id: null" | Cliente fora da lista mandando mensagem direto pro bot | Comportamento esperado: 3 inválidas → para. Para silenciar, filtre por `agendamento != None` antes de classificar |
| Django retorna 400 "Disallowed Host" para `host.docker.internal` | `ALLOWED_HOSTS` faltando entrada | `dmais_portal/core/settings.py`: `ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'host.docker.internal']` |
| Bot manda mensagem com data passada (ex: "06/01" em maio) | Adapter `_adapt()` não bumpando para amanhã | Verificar `worker/main.py::_adapt()` tem a checagem `< date.today()` → `today + timedelta(days=1)` |
| Cliente recebe 2 mensagens em rajada após texto livre | Versão antiga do `_handle_invalid` (fallback + reenvio separados) | Deve estar unificado: 1 mensagem só com prefix `"Desculpe, não entendi sua resposta. 🙏\n\n"` + menu inicial |

### Ordem para subir tudo do zero

```bash
# 1. Worker stack (Docker)
cd dmais_bot_engine
cp .env.example .env   # editar com credenciais
docker compose up -d --build
docker inspect -f '{{.State.Health.Status}}' dmais_worker   # esperar "healthy"

# 2. Pareamento WhatsApp (se primeira vez ou sessão perdida)
curl -X POST http://localhost:8080/instance/create -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"instanceName":"dmais","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
# Salvar o base64 como PNG e escanear

# 3. Django (host, fora do Docker)
cd ..\dmais_portal
$env:LR_DASHBOARD_TOKEN = "<mesmo token DRF do worker>"
.\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001 --noreload

# 4. Sanity check
curl http://localhost:8000/health                # worker
curl -H "Authorization: Token <t>" http://localhost:8001/api/logistica-reversa/pendentes-recolha/  # Django
```

### O que NUNCA fazer ao retomar

- ❌ `docker compose down -v` ou `make clean` — apaga sessão WhatsApp e Postgres do Evolution. Re-pareamento manual obrigatório.
- ❌ `git commit`/`push` no `dmais_portal/` — esse repo é controlado exclusivamente pelo usuário.
- ❌ Deletar o volume `dmais_evolution_instances`.
- ❌ Rodar `redis-cli FLUSHDB` no Redis enquanto há conversas em andamento — perde os estados intermediários.
- ❌ Subir o motor sem conferir `MAX_MESSAGES_PER_MINUTE=4` no `.env` (anti-bloqueio WhatsApp). Valor default antigo (30) pode causar shadowban.

---

## Demo dataset (hardcoded for sprint)

`worker/payloads/list_initial.py` has two hardcoded constants for the current sprint, to be replaced by real Django integration later:

- `SLOTS_DEMO` — 4 period slots (currently unused; left for reference)
- `DATAS_REMARCAR_DEMO` — 3 dates offered when the customer picks REMARCAR (`2026-05-19`, `2026-05-20`, `2026-05-21`)

When the customer picks REMARCAR, the bot offers these 3 dates, then asks for period (MANHA/TARDE). Future work: pull these from `GET /slots/<agendamento_id>/` on the Django side.
