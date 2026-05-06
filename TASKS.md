# TASKS — `dmais_bot_engine` (Sprint C)

> **Guia de execução passo a passo.** Marque cada item com `[x]` ao concluir.
> Cada task gera um commit isolado e deve ser validada antes de avançar.
> Referência completa de requisitos: ver [PRD.md](./PRD.md).

---

## Legenda de status

- `[ ]` pendente
- `[~]` em andamento
- `[x]` concluído
- `[!]` bloqueado (anotar motivo abaixo do item)

---

## Bloco 1 — Bootstrap do repositório

### 10.C.1 — Inicializar repositório Git e `.gitignore`
- [ ] `git init` na raiz `dmais_bot_engine/`
- [ ] Criar `.gitignore` otimizado para Python (venv, `__pycache__`, `.env`, `*.pyc`, `.idea/`, `.vscode/`, `dist/`, `build/`, `*.egg-info`, `htmlcov/`, `.pytest_cache/`, `.coverage`)
- [ ] Primeiro commit: `chore: bootstrap repo`

### 10.C.2 — README.md detalhado
- [ ] Criar `README.md` cobrindo:
  - [ ] Visão geral e arquitetura (resumo do PRD)
  - [ ] Pré-requisitos (Docker, Docker Compose, Make)
  - [ ] Setup (`cp .env.example .env`, `make up`)
  - [ ] **Pareamento WhatsApp via QRCode** (passo a passo de criação da instância na EvolutionAPI e leitura do QR)
  - [ ] Tabela de variáveis de ambiente
  - [ ] Comandos do Makefile
  - [ ] Troubleshooting comum

### 10.C.3 — `.env.example`
- [ ] Criar arquivo com TODAS as variáveis (com comentários explicando cada uma):
  - [ ] `DJANGO_API_BASE_URL`
  - [ ] `DJANGO_API_TOKEN`
  - [ ] `EVOLUTION_API_URL`
  - [ ] `EVOLUTION_API_KEY`
  - [ ] `EVOLUTION_INSTANCE_NAME`
  - [ ] `REDIS_URL`
  - [ ] `POLLING_INTERVAL_SECONDS`
  - [ ] `MAX_MESSAGES_PER_MINUTE`
  - [ ] `LOG_LEVEL`
  - [ ] `WORKER_HTTP_PORT`
- [ ] Garantir que `.env` real está no `.gitignore`

---

## Bloco 2 — Infraestrutura Docker

### 10.C.4 — `docker-compose.yml` (3 serviços)
- [ ] Definir versão do compose
- [ ] Serviço `evolution-api` (`atendai/evolution-api:latest`)
  - [ ] Mapear porta do gateway
  - [ ] Variáveis de ambiente mínimas exigidas pela imagem
- [ ] Serviço `redis` (`redis:7-alpine`)
  - [ ] AOF habilitado (`--appendonly yes`)
- [ ] Serviço `worker` (build local em `./worker`)
  - [ ] `depends_on` com `condition: service_healthy` em `redis` e `evolution-api`
  - [ ] Carregar `.env`
- [ ] Rede compose interna nomeada (`dmais_net`)

### 10.C.5 — Volumes persistentes nomeados
- [ ] `evolution-instances` montado em `/evolution/instances` no container Evolution
- [ ] `evolution-store` montado em `/evolution/store` no container Evolution
- [ ] `redis-data` montado em `/data` no container Redis
- [ ] Documentar no README como fazer backup/restore desses volumes

### 10.C.6 — Healthchecks no compose
- [ ] `redis`: `redis-cli ping` a cada 10 s
- [ ] `evolution-api`: HTTP GET na rota raiz/`/manager` a cada 15 s
- [ ] `worker`: HTTP GET em `/health` (porta interna) a cada 15 s
- [ ] Definir `start_period` adequado (Evolution leva ~30 s para subir)

---

## Bloco 3 — Imagem do Worker

### 10.C.7 — `worker/Dockerfile`
- [ ] Base `python:3.11-slim`
- [ ] Instalar dependências do sistema mínimas (`build-essential` se necessário, ou `gcc` apenas em estágio de build se usar multi-stage)
- [ ] Copiar `requirements.txt` antes do código (cache de layer)
- [ ] `pip install --no-cache-dir -r requirements.txt`
- [ ] Copiar código do worker
- [ ] `EXPOSE ${WORKER_HTTP_PORT}` (ou valor fixo 8000)
- [ ] `CMD` rodando `uvicorn worker.main:app --host 0.0.0.0 --port 8000`
- [ ] Usuário não-root

### 10.C.8 — `worker/requirements.txt`
- [ ] `httpx`
- [ ] `pydantic`
- [ ] `pydantic-settings`
- [ ] `redis`
- [ ] `structlog`
- [ ] `python-dotenv`
- [ ] `tenacity`
- [ ] `fastapi`
- [ ] `uvicorn[standard]`
- [ ] Pinnar versões (semver compatível)

---

## Bloco 4 — Núcleo do Worker

### 10.C.9 — Pacote `worker/` e `settings.py`
- [ ] Criar `worker/__init__.py` (vazio)
- [ ] Criar `worker/settings.py`:
  - [ ] Classe `Settings(BaseSettings)` com todas as envs do PRD §5
  - [ ] Validações (URLs, ints, log level)
  - [ ] Singleton `settings = Settings()` exportado

### 10.C.10 — `worker/logs.py`
- [ ] Configurar `structlog` em modo JSON
- [ ] Processador para injetar `correlation_id` (via `contextvars`)
- [ ] Helper `bind_correlation_id(cid)` e `new_correlation_id()`
- [ ] Filtro para mascarar `Authorization` e dados sensíveis

### 10.C.11 — `worker/api_client.py` (Django)
- [ ] Cliente `httpx.AsyncClient` reaproveitável
- [ ] Header `Authorization: Token {DJANGO_API_TOKEN}` em todas as chamadas
- [ ] Decorador `tenacity.retry` (backoff exponencial, max 5 tentativas, retry em `httpx.HTTPError` e 5xx)
- [ ] Métodos:
  - [ ] `async def listar_pendentes(page: int) -> dict`
  - [ ] `async def listar_slots(agendamento_id: int) -> list[dict]`
  - [ ] `async def post_webhook(payload: dict) -> None`
- [ ] Logging de cada chamada com `correlation_id`

### 10.C.13 — `worker/redis_queue.py`
- [ ] Conexão Redis assíncrona (`redis.asyncio`)
- [ ] Função `is_duplicate_event(event_id) -> bool` (`SET evt:<id> 1 NX EX 86400`)
- [ ] Função `mark_sent(agendamento_id)` / `was_sent(agendamento_id)` com TTL 24h
- [ ] Contador de erros: `incr_error(chat_id) -> int` / `reset_error(chat_id)`
- [ ] Funções utilitárias para fila de retry (LPUSH/BRPOP) — opcional para futuro

### 10.C.14 — `worker/evolution_client.py`
- [ ] Cliente `httpx.AsyncClient` para EvolutionAPI
- [ ] Header `apikey: {EVOLUTION_API_KEY}`
- [ ] **Rate limit token bucket** baseado em Redis (chaves `ratelimit:bucket`, `ratelimit:last_refill`)
- [ ] Método `acquire()` que aguarda assincronamente até haver token disponível
- [ ] Método `send_list_message(payload: dict) -> dict` que chama `acquire()` antes de POST
- [ ] Tratamento de erros e logging
- [ ] Capacidade configurável via `MAX_MESSAGES_PER_MINUTE`

---

## Bloco 5 — Payloads

### 10.C.15 — `worker/payloads/list_initial.py`
- [ ] Função `build_initial_list(agendamento: dict) -> dict`
- [ ] Monta payload conforme PRD §6.1 (3 rows: CONFIRMAR, REMARCAR, JA_ENTREGUE)
- [ ] Validação: nunca incluir URLs no texto
- [ ] Tipos via `pydantic` (opcional mas recomendado)

### 10.C.16 — `worker/payloads/list_horarios.py`
- [ ] Função `build_horarios_list(agendamento: dict, slots: list[dict]) -> dict`
- [ ] Limita a 10 slots máximo (`slots[:10]`)
- [ ] `rowId` = `SLOT:<iso8601>`
- [ ] Formata `title` legível em pt-BR (ex.: `"Seg 12/05 às 09h-11h"`)

---

## Bloco 6 — Handlers de fluxo

### 10.C.17 — Handler `enviar_inicial`
- [ ] Arquivo `worker/handlers/enviar_inicial.py`
- [ ] Função `async def handle(agendamento: dict) -> None`
- [ ] Verifica `was_sent`, monta payload via `list_initial`, chama `evolution_client.send_list_message`, marca `sent:<id>`
- [ ] Logs com `correlation_id` único por agendamento

### 10.C.18 — Handler `enviar_slots`
- [ ] Arquivo `worker/handlers/enviar_slots.py`
- [ ] Função `async def handle(agendamento_id: int, telefone: str) -> None`
- [ ] Chama `api_client.listar_slots`, monta payload via `list_horarios`, envia via Evolution
- [ ] Trata caso "sem slots disponíveis" → envia mensagem texto neutra E posta `FALHA` no Django

### 10.C.19 — Handler `on_response` (webhook)
- [ ] Arquivo `worker/handlers/on_response.py`
- [ ] Função `async def handle(evolution_event: dict) -> None`
- [ ] Idempotência via `is_duplicate_event`
- [ ] Classifica evento:
  - [ ] List reply com `rowId` válido (`CONFIRMAR`, `REMARCAR`, `JA_ENTREGUE`, `SLOT:*`)
  - [ ] Texto livre / opção desconhecida
- [ ] Para `REMARCAR`: chama `enviar_slots`
- [ ] Para `SLOT:*`: extrai ISO e posta no Django
- [ ] Para inválidos: incrementa erro, envia fallback, reenvia inicial; ao atingir 3, posta `FALHA`
- [ ] Sempre posta evento canônico no Django

### 10.C.20 — Handler `on_timeout`
- [ ] Arquivo `worker/handlers/on_timeout.py`
- [ ] Função `async def handle(agendamento_id: int) -> None`
- [ ] Acionado pelo polling quando o Django sinaliza estado `TIMEOUT`
- [ ] Posta evento `FALHA` no Django e limpa contadores Redis

---

## Bloco 7 — Orquestração

### 10.C.21 — `worker/main.py`
- [ ] Instanciar `FastAPI(title="dmais_bot_engine")`
- [ ] Lifespan que sobe o **poller** como task assíncrona em background
- [ ] Endpoint `POST /webhook/evolution` → `on_response.handle`
- [ ] Endpoint `GET /health` → ver 10.C.24
- [ ] Loop de polling:
  - [ ] `while True: page = 1; iterar paginação; para cada agendamento → `enviar_inicial`; sleep `POLLING_INTERVAL_SECONDS`
  - [ ] Tratar exceções para que o loop **não morra**
- [ ] Shutdown graceful (fecha clients httpx e redis)

### 10.C.22 — Configurar webhook da EvolutionAPI
- [ ] Documentar no README a chamada `POST /webhook/set/{instance}` apontando para `http://worker:{WORKER_HTTP_PORT}/webhook/evolution`
- [ ] Eventos a habilitar: `MESSAGES_UPSERT`, `CONNECTION_UPDATE`
- [ ] Opcional: script `scripts/setup_webhook.sh` (curl) idempotente

### 10.C.24 — Endpoint `/health`
- [ ] `GET /health` retorna 200 com `{"status":"ok","redis":"<ok|fail>","evolution":"<ok|fail>"}`
- [ ] Faz ping no Redis e GET leve na Evolution
- [ ] Usado pelo healthcheck do `docker-compose.yml`

---

## Bloco 8 — Ferramental

### 10.C.26 — `Makefile`
- [ ] `make up` → `docker compose up -d --build`
- [ ] `make down` → `docker compose down`
- [ ] `make logs` → `docker compose logs -f --tail=200`
- [ ] `make restart` → `docker compose restart worker`
- [ ] `make test-send` → comando curl/python script que dispara um agendamento fake através do worker (rota interna de debug ou direto na Evolution) para validar setup
- [ ] `make qrcode` (bônus) → abre/curl a rota da Evolution que retorna o QR da instância

---

## Critérios globais de "Pronto"

- [ ] `docker compose up -d` sobe tudo sem erro e healthchecks ficam `healthy`
- [ ] Pareamento WhatsApp funcional via QRCode
- [ ] Polling consome `/pendentes-recolha/` paginado e dispara List Messages
- [ ] Rate limit não permite mais de 30 msg/min em testes de carga local
- [ ] Webhook idempotente (reenviar mesmo evento 2x não duplica chamada ao Django)
- [ ] Resposta `REMARCAR` gera List de slots
- [ ] Texto livre 3x consecutivas → `FALHA` ao Django
- [ ] Logs JSON com `correlation_id` em stdout
- [ ] README permite que outro dev suba o ambiente do zero em < 10 minutos

---

## Notas de execução

- Commits pequenos e atômicos por subtarefa.
- Variáveis sensíveis nunca commitadas — apenas `.env.example`.
- Toda PR deve referenciar o item 10.C.x correspondente.
