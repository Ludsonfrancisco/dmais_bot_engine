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
- [x] `git init` na raiz `dmais_bot_engine/`
- [x] Criar `.gitignore` otimizado para Python (venv, `__pycache__`, `.env`, `*.pyc`, `.idea/`, `.vscode/`, `dist/`, `build/`, `*.egg-info`, `htmlcov/`, `.pytest_cache/`, `.coverage`)
- [x] Primeiro commit: `chore: bootstrap repo`

### 10.C.2 — README.md detalhado
- [x] Criar `README.md` cobrindo:
  - [x] Visão geral e arquitetura (resumo do PRD)
  - [x] Pré-requisitos (Docker, Docker Compose, Make)
  - [x] Setup (`cp .env.example .env`, `make up`)
  - [x] **Pareamento WhatsApp via QRCode** (passo a passo de criação da instância na EvolutionAPI e leitura do QR)
  - [x] Tabela de variáveis de ambiente
  - [x] Comandos do Makefile
  - [x] Troubleshooting comum

### 10.C.3 — `.env.example`
- [x] Criar arquivo com TODAS as variáveis (com comentários explicando cada uma):
  - [x] `DJANGO_API_BASE_URL`
  - [x] `DJANGO_API_TOKEN`
  - [x] `EVOLUTION_API_URL`
  - [x] `EVOLUTION_API_KEY`
  - [x] `EVOLUTION_INSTANCE_NAME`
  - [x] `REDIS_URL`
  - [x] `POLLING_INTERVAL_SECONDS`
  - [x] `MAX_MESSAGES_PER_MINUTE`
  - [x] `LOG_LEVEL`
  - [x] `WORKER_HTTP_PORT`
- [x] Garantir que `.env` real está no `.gitignore`

---

## Bloco 2 — Infraestrutura Docker

### 10.C.4 — `docker-compose.yml` (3 serviços)
- [x] Definir versão do compose
- [x] Serviço `evolution-api` (`atendai/evolution-api:latest`)
  - [x] Mapear porta do gateway
  - [x] Variáveis de ambiente mínimas exigidas pela imagem
- [x] Serviço `redis` (`redis:7-alpine`)
  - [x] AOF habilitado (`--appendonly yes`)
- [x] Serviço `worker` (build local em `./worker`)
  - [x] `depends_on` com `condition: service_healthy` em `redis` e `evolution-api`
  - [x] Carregar `.env`
- [x] Rede compose interna nomeada (`dmais_net`)

### 10.C.5 — Volumes persistentes nomeados
- [x] `evolution-instances` montado em `/evolution/instances` no container Evolution
- [x] `evolution-store` montado em `/evolution/store` no container Evolution
- [x] `redis-data` montado em `/data` no container Redis
- [x] Documentar no README como fazer backup/restore desses volumes

### 10.C.6 — Healthchecks no compose
- [x] `redis`: `redis-cli ping` a cada 10 s
- [x] `evolution-api`: HTTP GET na rota raiz/`/manager` a cada 15 s
- [x] `worker`: HTTP GET em `/health` (porta interna) a cada 15 s
- [x] Definir `start_period` adequado (Evolution leva ~30 s para subir)

---

## Bloco 3 — Imagem do Worker

### 10.C.7 — `worker/Dockerfile`
- [x] Base `python:3.11-slim`
- [x] Instalar dependências do sistema mínimas (`curl`)
- [x] Copiar `requirements.txt` antes do código (cache de layer)
- [x] `pip install --no-cache-dir -r requirements.txt`
- [x] Copiar código do worker
- [x] `EXPOSE 8000`
- [x] `CMD` rodando `uvicorn worker.main:app --host 0.0.0.0 --port 8000`
- [x] Usuário não-root (`appuser` uid/gid 1000)

### 10.C.8 — `worker/requirements.txt`
- [x] `httpx`
- [x] `pydantic`
- [x] `pydantic-settings`
- [x] `redis`
- [x] `structlog`
- [x] `python-dotenv`
- [x] `tenacity`
- [x] `fastapi`
- [x] `uvicorn[standard]`
- [x] Versões pinadas (semver compatível)

---

## Bloco 4 — Núcleo do Worker

### 10.C.9 — Pacote `worker/` e `settings.py`
- [x] Criar `worker/__init__.py` (vazio)
- [x] Criar `worker/settings.py`:
  - [x] Classe `Settings(BaseSettings)` com todas as envs do PRD §5
  - [x] Validações (URLs, ints, log level)
  - [x] Singleton `settings = Settings()` exportado

### 10.C.10 — `worker/logs.py`
- [x] Configurar `structlog` em modo JSON
- [x] Processador para injetar `correlation_id` (via `contextvars`)
- [x] Helper `bind_correlation_id(cid)` e `new_correlation_id()`
- [x] Filtro para mascarar header `Authorization` antes de serializar
- [x] Filtro para mascarar campo `telefone`: exibir apenas últimos 4 dígitos (`"****8888"`)
- [x] Garantir que payloads brutos do Evolution só apareçam em `level=DEBUG` (LGPD)

### 10.C.11 — `worker/api_client.py` (Django)
- [x] Cliente `httpx.AsyncClient` reaproveitável
- [x] Header `Authorization: Token {DJANGO_API_TOKEN}` em todas as chamadas
- [x] Decorador `tenacity.retry` (backoff exponencial, max 5 tentativas, retry em 5xx e erros de rede; 4xx não retentado)
- [x] Métodos:
  - [x] `async def listar_pendentes(page: int) -> dict`
  - [x] `async def listar_slots(agendamento_id: int) -> list[dict]`
  - [x] `async def post_webhook(payload: dict) -> None`
- [x] Logging de cada chamada com `correlation_id`

### 10.C.13 — `worker/redis_queue.py`
- [x] Conexão Redis assíncrona (`redis.asyncio`)
- [x] Função `is_duplicate_event(event_id) -> bool` (`SET evt:<id> 1 NX EX 86400`)
- [x] Função `mark_sent(agendamento_id)` / `was_sent(agendamento_id)` com TTL 24h
- [x] Contador de erros: `incr_error(chat_id) -> int` / `reset_error(chat_id)`
- [x] Funções utilitárias para fila de retry (LPUSH/BRPOP) — opcional para futuro

### 10.C.14 — `worker/evolution_client.py`
- [x] Cliente `httpx.AsyncClient` para EvolutionAPI
- [x] Header `apikey: {EVOLUTION_API_KEY}`
- [x] **Rate limit token bucket** baseado em Redis (chaves `ratelimit:bucket`, `ratelimit:last_refill`)
- [x] Método `acquire()` que aguarda assincronamente até haver token disponível
- [x] Método `send_list_message(payload: dict) -> dict` que chama `acquire()` antes de POST
- [x] Tratamento de erros e logging
- [x] Capacidade configurável via `MAX_MESSAGES_PER_MINUTE`

---

## Bloco 5 — Payloads

### 10.C.15 — `worker/payloads/list_initial.py`
- [x] Função `build_initial_list(agendamento: dict) -> dict`
- [x] Monta payload conforme PRD §6.1 (3 rows: CONFIRMAR, REMARCAR, JA_ENTREGUE)
- [x] Validação: nunca incluir URLs no texto
- [x] Tipos via `pydantic` (opcional mas recomendado) — pure function + dict, sem overhead pydantic

### 10.C.16 — `worker/payloads/list_horarios.py`
- [x] Função `build_horarios_list(agendamento: dict, slots: list[dict]) -> dict`
- [x] Limita a 10 slots máximo (`slots[:10]`)
- [x] `rowId` = `SLOT:<iso8601>`
- [x] Formata `title` legível em pt-BR (ex.: `"Seg 12/05 às 09h-11h"`)

---

## Bloco 6 — Handlers de fluxo

### 10.C.17 — Handler `enviar_inicial`
- [x] Arquivo `worker/handlers/enviar_inicial.py`
- [x] Função `async def handle(agendamento: dict) -> None`
- [x] Verifica `was_sent`, monta payload via `list_initial`, chama `evolution_client.send_list_message`, marca `sent:<id>`
- [x] Logs com `correlation_id` único por agendamento

### 10.C.18 — Handler `enviar_slots`
- [x] Arquivo `worker/handlers/enviar_slots.py`
- [x] Função `async def handle(agendamento_id: int, telefone: str) -> None`
- [x] Chama `api_client.listar_slots`, monta payload via `list_horarios`, envia via Evolution
- [x] Trata caso "sem slots disponíveis" → envia mensagem texto neutra E posta `FALHA` no Django

### 10.C.19 — Handler `on_response` (webhook)
- [x] Arquivo `worker/handlers/on_response.py`
- [x] Função `async def handle(evolution_event: dict) -> None`
- [x] Idempotência via `is_duplicate_event`
- [x] Classifica evento:
  - [x] List reply com `rowId` válido (`CONFIRMAR`, `REMARCAR`, `JA_ENTREGUE`, `SLOT:*`)
  - [x] Texto livre / opção desconhecida
- [x] Para `REMARCAR`: chama `enviar_slots`
- [x] Para `SLOT:*`: extrai ISO e posta no Django
- [x] Para inválidos: incrementa erro, envia fallback, reenvia inicial; ao atingir 3, posta `FALHA`
- [x] Sempre posta evento canônico no Django

### 10.C.20 — Handler `on_timeout`
- [x] Arquivo `worker/handlers/on_timeout.py`
- [x] Função `async def handle(agendamento_id: int) -> None`
- [x] Acionado pelo polling quando o Django sinaliza estado `TIMEOUT`
- [x] Posta evento `FALHA` no Django e limpa contadores Redis

---

## Bloco 7 — Orquestração

### 10.C.21 — `worker/main.py`
- [x] Instanciar `FastAPI(title="dmais_bot_engine")`
- [x] Lifespan que sobe o **poller** como task assíncrona em background
- [x] Endpoint `POST /webhook/evolution` → `on_response.handle`
- [x] Endpoint `GET /health` → ver 10.C.24
- [x] Endpoint `POST /debug/test-send` → ver 10.C.25
- [x] Loop de polling:
  - [x] `while True: page = 1; iterar paginação completa via campo `next``
  - [x] Para cada agendamento com `status == "PENDENTE_CONFIRMACAO"` → `enviar_inicial.handle(agendamento)`
  - [x] Para cada agendamento com `status == "TIMEOUT"` → `on_timeout.handle(agendamento_id)`
  - [x] Qualquer outro status: ignorar silenciosamente
  - [x] Tratar exceções para que o loop **nunca morra** (logar erro e continuar)
- [x] Shutdown graceful (fecha clients httpx e redis)

### 10.C.22 — Configurar webhook da EvolutionAPI
- [x] Webhook global configurado via variáveis de ambiente no `docker-compose.yml`:
  - [x] `WEBHOOK_GLOBAL_URL=http://worker:{WORKER_HTTP_PORT}/webhook/evolution`
  - [x] `WEBHOOK_GLOBAL_ENABLED=true`
  - [x] `WEBHOOK_EVENTS_MESSAGES_UPSERT=true` e `WEBHOOK_EVENTS_CONNECTION_UPDATE=true`
- [x] Finalizar `scripts/setup_webhook.sh`: curl ativado para `POST /webhook/set/{instance}` com validação de HTTP code (útil para forçar reconfiguração manual sem restartar o compose)

### 10.C.24 — Endpoint `/health`
- [x] `GET /health` retorna 200 com `{"status":"ok","redis":"<ok|fail>","evolution":"<ok|fail>"}`
- [x] Faz ping no Redis e GET leve na Evolution
- [x] Usado pelo healthcheck do `docker-compose.yml`

### 10.C.25 — Endpoint `/debug/test-send`
- [x] `POST /debug/test-send` aceita `{"telefone": str, "nome": str, "data": str, "hora": str}`
- [x] Monta agendamento sintético (sem consultar Django) e chama `enviar_inicial.handle()`
- [x] Retorna `{"status": "ok", "evolution_response": {...}}` ou HTTP 500 com detalhe do erro
- [x] Usado por `make test-send` para validar setup end-to-end após pareamento WhatsApp

---

## Bloco 8 — Ferramental

### 10.C.26 — `Makefile`
- [x] `make up` → `docker compose up -d --build`
- [x] `make down` → `docker compose down`
- [x] `make logs` → `docker compose logs -f --tail=200`
- [x] `make restart` → `docker compose restart worker`
- [x] `make test-send` → POST em `/debug/test-send` com agendamento sintético
- [x] `make qrcode` → curl na rota da Evolution que retorna o QR da instância

---

## Bloco 9 — Testes e Simulação

### 10.C.27 — Infraestrutura de testes
- [x] Adicionar ao `worker/requirements.txt`: `pytest>=8.0`, `pytest-asyncio>=0.23`, `fakeredis>=2.20`
- [x] Criar `worker/tests/__init__.py`
- [x] Criar `worker/pytest.ini`:
  - [x] `asyncio_mode = auto` (pytest-asyncio)
  - [x] `testpaths = tests`
- [x] Adicionar `make test` ao Makefile → `docker compose exec worker python -m pytest tests/ -v`
- [x] Adicionar `make demo` ao Makefile → sobe stack + aguarda healthcheck + dispara test-send + tails logs

### 10.C.28 — Testes unitários dos módulos core
- [x] `worker/tests/test_logs.py`
  - [x] `telefone` curto (≤ 4 dígitos) não é mascarado
  - [x] `telefone` longo → `"****XXXX"`
  - [x] `Authorization` top-level → `"***"`
  - [x] `Authorization` em dict `headers` → `"***"`
  - [x] `correlation_id` injetado após `new_correlation_id()`
  - [x] `bind_correlation_id` substitui o valor anterior
- [x] `worker/tests/test_settings.py`
  - [x] `LOG_LEVEL` inválido → `ValidationError`
  - [x] `POLLING_INTERVAL_SECONDS=0` → `ValidationError`
  - [x] `DJANGO_API_BASE_URL` com barra final → armazenado sem barra
- [x] `worker/tests/test_payloads.py` *(implementar após 10.C.15 e 10.C.16)*
  - [x] `build_initial_list` → payload com exatamente 3 rows (CONFIRMAR, REMARCAR, JA_ENTREGUE)
  - [x] `build_initial_list` → nenhum campo contém URL
  - [x] `build_horarios_list` com 12 slots → payload com exatamente 10 rows
  - [x] `build_horarios_list` → `rowId` começa com `SLOT:`
  - [x] `build_horarios_list` → `title` em pt-BR (ex.: `"Seg 12/05 às 09h-11h"`)
- [x] `worker/tests/test_redis_queue.py` *(implementar após 10.C.13, usa fakeredis)*
  - [x] `is_duplicate_event` retorna `False` na 1ª chamada e `True` na 2ª com mesmo ID
  - [x] `mark_sent` / `was_sent` seguem mesmo padrão
  - [x] `incr_error` retorna 1, 2, 3 em chamadas consecutivas
  - [x] `reset_error` zera o contador
- [x] `worker/tests/test_on_response.py` *(implementar após 10.C.19, usa mocks)*
  - [x] `rowId=CONFIRMAR` → chama `post_webhook` com `tipo="CONFIRMAR"`
  - [x] `rowId=REMARCAR` → chama `enviar_slots.handle`
  - [x] `rowId=JA_ENTREGUE` → chama `post_webhook` com `tipo="JA_ENTREGUE"`
  - [x] `rowId=SLOT:2026-05-12T09:00:00-03:00` → chama `post_webhook` com `slot_escolhido` correto
  - [x] Texto livre 2x → reenvia lista inicial; na 3ª → `post_webhook` com `tipo="FALHA"`
  - [x] Evento duplicado (mesmo `event_id`) → não chama `post_webhook` segunda vez

### 10.C.29 — Simulação visível end-to-end
- [ ] Executar `make demo` com stack rodando e WhatsApp pareado
- [ ] Verificar no terminal: log JSON com `correlation_id`, `telefone` mascarado, resposta da EvolutionAPI
- [ ] Verificar no WhatsApp: mensagem List interativa recebida com 3 opções (CONFIRMAR / REMARCAR / JÁ ENTREGUEI)
- [ ] Responder `CONFIRMAR` no WhatsApp e verificar log do webhook recebido pelo worker
- [ ] Verificar que `make health` retorna `{"status":"ok","redis":"ok","evolution":"ok"}`

---

## Critérios globais de "Pronto"

- [ ] `docker compose up -d` sobe tudo sem erro e healthchecks ficam `healthy`
- [ ] Pareamento WhatsApp funcional via QRCode
- [ ] Polling consome `/pendentes-recolha/` paginado e dispara List Messages
- [ ] Rate limit não permite mais de 5 msg/min em testes de carga local e usar sleep randomico, nao ser a cada 12 seg cravados.
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

---

## Rodapé — Checklist 10.C.29: Simulação End-to-End

> Execute cada etapa em ordem. Cole a saída de cada comando no chat para acompanhamento.

### Etapa 1 — Preparar `.env`

```bash
cp .env.example .env
```

Preencha **obrigatoriamente** no `.env`:
- [ ] `DJANGO_API_BASE_URL` — URL da API Django (ex.: `https://api.dmais.com.br`)
- [ ] `DJANGO_API_TOKEN` — token de auth do Django
- [ ] `EVOLUTION_API_KEY` — string segura (ex.: `minha-chave-123`)
- [ ] `EVOLUTION_INSTANCE_NAME` — deixe `dmais` ou escolha outro nome

> `REDIS_URL`, `EVOLUTION_API_URL`, `POLLING_INTERVAL_SECONDS` etc. ficam com os defaults.

---

### Etapa 2 — Subir a stack

```bash
make up
```

Aguarde ~30s e verifique:
```bash
make ps
```

- [ ] `evolution-api` → `healthy`
- [ ] `redis` → `healthy`
- [ ] `worker` → `healthy`

> Se algum ficar `starting` por mais de 60s, cole o output de `make logs`.

---

### Etapa 3 — Parear WhatsApp via QRCode

```bash
make qrcode
```

- [ ] Resposta JSON contém campo `qrcode` ou `base64`
- [ ] Abriu WhatsApp no celular → `Dispositivos conectados` → `Conectar dispositivo` → escaneou o QR
- [ ] Rodou `make qrcode` novamente e o campo `state` está `open` (conectado)

> Dica: se o QR vier em base64, acesse `http://localhost:8080/manager` no browser para ver o painel da EvolutionAPI.

---

### Etapa 4 — Disparar mensagem de teste

Substitua `55119XXXXXXXX` pelo seu número real (com código do país):

```bash
curl -s -X POST \
  "http://localhost:8000/debug/test-send" \
  -H "Content-Type: application/json" \
  -d '{"telefone":"55119XXXXXXXX","nome":"Teste","data":"2026-05-08","hora":"14:00"}' \
  | python -m json.tool
```

- [ ] Resposta JSON contém `"status": "ok"` e `"evolution_response": {...}`
- [ ] No celular chegou mensagem WhatsApp com lista de 3 opções (Confirmar / Remarcar / Já entreguei)

---

### Etapa 5 — Verificar logs do disparo

```bash
make logs-worker
```

- [ ] Log contém campo `correlation_id` (UUID)
- [ ] Campo `telefone` aparece mascarado: `"****XXXX"` (apenas últimos 4 dígitos)
- [ ] Log de `evolution.send` com `"level": "info"`

---

### Etapa 6 — Responder no WhatsApp e verificar webhook

Toque em **Confirmar coleta** na mensagem recebida no celular.

- [ ] Novo log aparece com `"event": "on_response.received"`
- [ ] Log contém `"tipo": "CONFIRMAR"`
- [ ] Log contém `"agendamento_id"`

---

### Etapa 7 — Health check final

```bash
make health
```

- [ ] Resposta: `{"status": "ok", "redis": "ok", "evolution": "ok"}`
