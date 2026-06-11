# dmais_bot_engine

> Motor WhatsApp DMais: originalmente criado para confirmação de coletas da Logística Reversa; fase atual: publicador de relatórios automáticos do dmais_portal em grupos WhatsApp.

---

## Visão Geral

> **Fase atual (Sprint Report Automation):** o `dmais_bot_engine` será estendido para enviar relatórios e prints das páginas **Backlog** e **Prazo de Atendimento** do `dmais_portal` em um **grupo WhatsApp de testes**. O envio para grupo oficial só será habilitado depois de homologação explícita.

O `dmais_bot_engine` é um **motor autocontido**, orquestrado via Docker Compose. O fluxo original de Logística Reversa continua preservado e é responsável por:

1. **Buscar agendamentos pendentes** na API Django (polling periódico, 60s).
2. **Enviar mensagens WhatsApp** (texto plano com opções numeradas, branding AT3 Internet) via EvolutionAPI (Baileys).
3. **Conduzir um diálogo multi-etapas** (confirmar → escolher período / remarcar → data + período / já entreguei → texto livre) — máquina de estados em Redis.
4. **Rotear respostas dos clientes** de volta ao Django via webhook (move kanban: PENDENTE_CONTATO → AGUARDANDO_CLIENTE → CONFIRMADO/REMARCADO/JA_ENTREGUE).
5. **Gerenciar filas e idempotência** com Redis (rate-limit 4 msg/min com jitter aleatório, idempotência por event_id, lock por chat).

O motor **não possui banco de dados próprio** — todo estado durável vive na API Django. O Redis serve como memória operacional (filas, duplicidade, rate limiting, **estado da conversa por telefone**).

### Fase Report Automation

Nesta fase, o bot passa a atuar também como **publicador de relatórios WhatsApp** conectado ao `dmais_portal`:

1. Captura prints autenticados das páginas `/backlog/` e `/prazo-atendimento/`.
2. Monta relatórios textuais a partir da base atual do portal.
3. Envia primeiro para `WHATSAPP_TEST_GROUP_JID`.
4. Só libera `WHATSAPP_REPORT_GROUP_JID` depois da homologação.
5. Agenda envios por cron usando `REPORT_TIMEZONE=America/Sao_Paulo`.

> ⚠️ **Mudança arquitetural (May 2026):** O PRD original especificava WhatsApp List Messages, mas a Meta as deprecou no protocolo Web/Multi-Device. O motor agora usa **texto plano com opções numeradas (1/2/3)** e máquina de estados multi-etapas. Detalhes técnicos completos em [CLAUDE.md](./CLAUDE.md).

### Arquitetura

```
┌─────────────────────┐             ┌───────────────────────┐
│  Django API (ext.)   │             │  WhatsApp (cliente)   │
│  /pendentes-recolha/ │             │                       │
│  /whatsapp-webhook/  │             └───────────┬───────────┘
└──────────┬──────────┘                         │ Baileys
           │ HTTPS + Token                      │
┌──────────▼────────────────────────────────────▼───────────┐
│                Docker Compose (host local)                 │
│                                                            │
│  ┌────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  worker    │◄─┤  evolution-api  │  │  redis         │  │
│  │  FastAPI + │  │  :8080          │  │  filas/idempt. │  │
│  │  poller    │─►│  (Baileys)      │  │  rate-limit    │  │
│  └────────────┘  └─────────────────┘  └────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

Para detalhes completos, consulte [PRD.md](./PRD.md).

---

## Pré-requisitos

| Ferramenta        | Versão mínima | Verificar                |
|-------------------|---------------|--------------------------|
| Docker            | 24.x          | `docker --version`       |
| Docker Compose    | v2.x          | `docker compose version` |
| Make (opcional)   | qualquer      | `make --version`         |
| Git               | 2.x           | `git --version`          |

---

## Setup Rápido

### 1. Clonar o repositório

```bash
git clone <url-do-repo> dmais_bot_engine
cd dmais_bot_engine
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` e preencha os valores reais:

| Variável                    | Descrição                                     | Default                     |
|-----------------------------|-----------------------------------------------|-----------------------------|
| `DJANGO_API_BASE_URL`       | URL base da API Django (sem barra final)      | —                           |
| `DJANGO_API_TOKEN`          | Token de autenticação `Authorization: Token`  | —                           |
| `EVOLUTION_API_URL`         | URL interna da EvolutionAPI                   | `http://evolution-api:8080` |
| `EVOLUTION_API_KEY`         | API key global da EvolutionAPI                | —                           |
| `EVOLUTION_INSTANCE_NAME`   | Nome da instância/sessão WhatsApp             | `dmais`                     |
| `POSTGRES_PASSWORD`         | Senha do Postgres interno da EvolutionAPI     | `evolution`                 |
| `REDIS_URL`                 | URL de conexão Redis                          | `redis://redis:6379/0`      |
| `POLLING_INTERVAL_SECONDS`  | Intervalo de polling (segundos)               | `60`                        |
| `MAX_MESSAGES_PER_MINUTE`   | Limite de envios por minuto (anti-bloqueio)   | `4`                         |
| `LOG_LEVEL`                 | Nível de log (`DEBUG`/`INFO`/`WARNING`/`ERROR`)| `INFO`                     |
| `WORKER_HTTP_PORT`          | Porta HTTP do worker (FastAPI)                | `8000`                      |
| `REPORTS_ENABLED`           | Liga/desliga crons de relatórios              | `false`                     |
| `REPORT_TARGETS`            | Destinos: `test`, `production`, `test,production` | `test`                  |
| `WHATSAPP_TEST_GROUP_JID`   | Grupo WhatsApp de homologação                 | —                           |
| `WHATSAPP_REPORT_GROUP_JID` | Grupo WhatsApp oficial                        | —                           |
| `REPORT_TIMEZONE`           | Timezone dos crons/relatórios                 | `America/Sao_Paulo`         |
| `DMAIS_PORTAL_URL`          | URL do portal para prints/dados               | `http://localhost:8001`     |
| `DMAIS_PORTAL_EMAIL`        | Email de login no portal                      | —                           |
| `DMAIS_PORTAL_PASSWORD`     | Senha de login no portal                      | —                           |

### 3. Subir e validar a stack

```bash
make up
make ps
make health
```

Todos os serviços (`postgres`, `evolution-api`, `redis`, `worker`) devem estar com status `healthy` em até 60 segundos.

### 4. Criar/parear a instância WhatsApp

```bash
set -a; . ./.env; set +a
curl -s -X POST "http://localhost:8080/instance/create" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"instanceName":"'"$EVOLUTION_INSTANCE_NAME"'","qrcode":true}' | python -m json.tool
make qrcode
xdg-open /tmp/dmais_qr.png  # opcional: abre a imagem gerada pelo make qrcode
```

Escaneie o QR no WhatsApp: Dispositivos conectados → Conectar dispositivo. Depois confirme:

```bash
curl -s -X GET "http://localhost:8080/instance/connectionState/$EVOLUTION_INSTANCE_NAME" \
  -H "apikey: $EVOLUTION_API_KEY" | python -m json.tool
```

O campo `state` deve ser `"open"`.

---

## Pareamento WhatsApp via QRCode

O pareamento conecta a EvolutionAPI a um número de WhatsApp real via QRCode.

### Passo a passo

1. **Suba os serviços** (se ainda não estiver rodando):
   ```bash
   make up
   ```

2. **Crie a instância** (apenas na primeira vez):
   ```bash
   set -a; . ./.env; set +a
   curl -s -X POST \
     "http://localhost:8080/instance/create" \
     -H "apikey: $EVOLUTION_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"instanceName":"'"$EVOLUTION_INSTANCE_NAME"'","qrcode":true}' | python -m json.tool
   ```

3. **Obtenha o QRCode** para escanear:
   ```bash
   make qrcode
   # ou:
   curl -s -X GET \
     "http://localhost:8080/instance/connect/$EVOLUTION_INSTANCE_NAME" \
     -H "apikey: $EVOLUTION_API_KEY" | python -m json.tool
   ```
   - O `make qrcode` salva a imagem em `/tmp/dmais_qr.png`; abra esse arquivo para escanear.

4. **Escaneie o QRCode** com o WhatsApp do número que será usado para enviar as mensagens:
   - Abra o WhatsApp → Dispositivos conectados → Conectar dispositivo → Escaneie o QR.

5. **Verifique a conexão**:
   ```bash
   curl -s -X GET \
     "http://localhost:8080/instance/connectionState/$EVOLUTION_INSTANCE_NAME" \
     -H "apikey: $EVOLUTION_API_KEY" | python -m json.tool
   ```
   - O campo `state` deve ser `"open"`.

> **⚠️ Importante:** A sessão WhatsApp é persistida no volume `evolution-instances`. **Não apague este volume**, ou será necessário parear novamente.

---

## Comandos do Makefile

| Comando           | Descrição                                          |
|-------------------|----------------------------------------------------|
| `make up`         | Sobe todos os serviços (com rebuild)               |
| `make down`       | Para containers (volumes preservados)              |
| `make logs`       | Logs em tempo real (últimas 200 linhas)            |
| `make logs-worker`| Logs apenas do worker                              |
| `make restart`    | Reinicia apenas o worker                           |
| `make build`      | Rebuild sem cache                                  |
| `make ps`         | Status dos containers e healthchecks               |
| `make health`     | Healthcheck manual do worker                       |
| `make shell-worker`| Shell bash dentro do container worker             |
| `make shell-redis`| Redis CLI dentro do container Redis                |
| `make qrcode`     | Obtém QRCode de pareamento da instância            |
| `make test-send`  | Envia mensagem de teste para validar setup         |
| `make clean`      | **⚠️ CUIDADO:** Remove tudo incluindo volumes      |

---

## Estrutura do Projeto

```
dmais_bot_engine/
├── .env.example              # Template de variáveis de ambiente
├── .gitignore                # Python + Docker + sensíveis
├── docker-compose.yml        # 4 serviços: postgres, evolution-api, redis, worker
├── Makefile                  # Atalhos operacionais
├── PRD.md                    # Product Requirements Document
├── TASKS.md                  # Guia de execução Sprint C (checkboxes)
├── README.md                 # Este arquivo
├── scripts/
│   └── setup_webhook.sh      # Configuração idempotente do webhook
└── worker/
    ├── Dockerfile            # python:3.11-slim + uvicorn
    ├── requirements.txt      # Dependências pinadas
    ├── __init__.py           # Pacote principal
    ├── settings.py           # Variáveis de ambiente (pydantic-settings)
    ├── logs.py               # structlog + correlation_id
    ├── api_client.py         # Cliente HTTP para Django (httpx + tenacity)
    ├── redis_queue.py        # Filas, idempotência, rate-limit (Redis)
    ├── evolution_client.py   # Cliente EvolutionAPI + token bucket
    ├── main.py               # FastAPI + polling loop
    ├── payloads/
    │   ├── __init__.py
    │   ├── list_initial.py   # Textos AT3: inicial (3 opções), período (manhã/tarde), datas remarcar
    │   └── list_horarios.py  # Legado: lista de slots (preservado para compat)
    └── handlers/
        ├── __init__.py
        ├── enviar_inicial.py # Pre-check (check_exists), envia inicial, transiciona Django
        ├── enviar_slots.py   # Legado: envio de horários
        ├── on_response.py    # State machine multi-etapas + lock por chat + @lid
        └── on_timeout.py     # Handler: timeout de agendamento
```

---

## Troubleshooting

### Container `evolution-api` não fica healthy

```bash
docker compose logs evolution-api --tail=50
```
- Verifique se `EVOLUTION_API_KEY` está definida no `.env`.
- A EvolutionAPI pode levar ~30s para inicializar. Aguarde.

### Worker não conecta ao Redis

```bash
docker compose exec worker python -c "import redis; r=redis.from_url('redis://redis:6379/0'); print(r.ping())"
```
- Verifique se o serviço `redis` está `healthy` (`make ps`).
- Confirme que `REDIS_URL` no `.env` aponta para `redis://redis:6379/0`.

### Sessão WhatsApp desconectou

```bash
make qrcode
```
- Escaneie novamente com o WhatsApp.
- Se o QR não aparece, reinicie a Evolution: `docker compose restart evolution-api`.

### Worker em loop de erro

```bash
make logs-worker
```
- Logs em JSON com `correlation_id` — busque o ID do fluxo com problema.
- Verifique se `DJANGO_API_BASE_URL` e `DJANGO_API_TOKEN` estão corretos.
- A API Django deve estar acessível de dentro do container.

### Limpar tudo e recomeçar

```bash
make clean  # ⚠️ Perde sessão WhatsApp e dados do Redis
make up
```

### Backup de volumes (sessão WhatsApp)

```bash
# Exportar
docker run --rm -v dmais_evolution_instances:/data -v $(pwd):/backup \
  alpine tar czf /backup/evolution-instances-backup.tar.gz -C /data .

# Restaurar
docker run --rm -v dmais_evolution_instances:/data -v $(pwd):/backup \
  alpine tar xzf /backup/evolution-instances-backup.tar.gz -C /data
```

---

## ⚠️ Retomar o projeto em outra máquina

Antes de subir a stack em nova máquina ou após reboot, leia o **checklist completo em [CLAUDE.md](./CLAUDE.md#retomar-o-projeto-em-outra-máquina--após-reboot)**. Resumo:

1. **`git pull`** dos dois repos (`dmais_bot_engine` + `dmais_portal` irmão).
2. **`dmais_portal` é controlado exclusivamente pelo usuário** — nunca rodar `git commit`/`push` ali sem autorização. Itens pendentes lá podem precisar ser pulled antes de subir.
3. **`.env`** não é versionado (gitignored). Recriar a partir de `.env.example` com:
   - `DJANGO_API_TOKEN` (gere com `python manage.py criar_token_motor --label <nome>` no portal)
   - `EVOLUTION_API_KEY` (qualquer string aleatória 32+ chars — vira a senha mestra)
4. **Sessão WhatsApp** vive em volume Docker local. Em máquina nova: re-parear via QR.
5. **Estados de conversa em Redis** são voláteis — em retomada limpa, clientes precisam responder do menu inicial novamente.

### O que NUNCA fazer

- ❌ `docker compose down -v` ou `make clean` — apaga sessão WhatsApp.
- ❌ `git commit`/`push` no `dmais_portal/` — repo exclusivo do usuário.
- ❌ Subir sem conferir `MAX_MESSAGES_PER_MINUTE=4` (anti-bloqueio).

---

## Referências

- [CLAUDE.md](./CLAUDE.md) — Guia técnico atual (arquitetura, internals, decisões).
- [FLOW.md](./FLOW.md) — Diagrama da máquina de estados conversacional + mensagens.
- [PRD.md](./PRD.md) — Documento de requisitos original (parte foi superada — ver CLAUDE.md).
- [TASKS.md](./TASKS.md) — Guia de execução Sprint C.
- [EvolutionAPI Docs](https://doc.evolution-api.com/) — Documentação oficial.
- [FastAPI Docs](https://fastapi.tiangolo.com/) — Framework do worker.
