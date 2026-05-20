# PRD — `dmais_bot_engine` (Motor Local de Disparo WhatsApp)

> **Versão:** 1.1
> **Data:** 2026-05-20
> **Owner:** Equipe DMais — Logística Reversa
> **Status:** Draft (pronto para Sprint C)

> ⚠️ **NOTA ARQUITETURAL IMPORTANTE** — O bot **NÃO usa List Messages do WhatsApp**. A Meta deprecou List Messages no protocolo Multi-Device (Baileys), e a implementação real usa **texto plano com opções numeradas (1/2/3)** via `sendText`. Respostas são classificadas por número (`"1"`, `"2"`, `"3"`) ou palavras-chave (`"confirmar"`, `"remarcar"`, `"ja entreguei"`), e não por `rowId` de List Message. Toda referência a `sendList`, `rowId` e "List Message" neste documento é mantida apenas para contexto histórico; a implementação segue exclusivamente `sendText` + texto numerado.

---

## 1. Visão Geral

O `dmais_bot_engine` é um **motor local autocontido**, executado via Docker Compose, responsável por automatizar a confirmação de coletas de logística reversa via WhatsApp. Ele atua como um **orquestrador desacoplado** entre:

- A **API Django** (sistema principal de logística — fora deste repositório), que detém os agendamentos e regras de negócio.
- A **EvolutionAPI** (gateway WhatsApp baseado em Baileys), que conecta a um número de telefone real via QRCode.
- O **Redis**, que armazena filas locais, idempotência de eventos e estado de conversa de curto prazo.

O motor **não possui banco de dados próprio**. Todo o estado durável vive na API Django; o Redis é apenas memória operacional do motor.

---

## 2. Objetivos

| # | Objetivo | Métrica de sucesso |
|---|----------|---------------------|
| O1 | Disparar mensagens WhatsApp de confirmação de coleta automaticamente | 100 % dos agendamentos elegíveis recebem a mensagem inicial dentro do intervalo de polling |
| O2 | Capturar respostas do cliente e roteá-las de volta ao Django | 0 webhooks perdidos; 100 % de idempotência em retries do Evolution |
|| O3 | Respeitar limites operacionais do WhatsApp | Nunca ultrapassar 4 msg/min por instância (anti-bloqueio) |
| O4 | Operar de forma resiliente sem intervenção manual | Reinício automático de containers; reconexão automática à EvolutionAPI |
| O5 | Ser portável e isolado | `docker compose up` em qualquer host com Docker, sem depender do projeto Django |

### Não-objetivos (Out of Scope)

- Persistir histórico de mensagens (responsabilidade do Django).
- Enviar mídias (imagens, áudios, documentos) — apenas mensagens de texto com opções numeradas.
- Multi-tenant: o motor opera **uma única instância EvolutionAPI** por deploy.
- UI de administração: configuração 100 % via `.env`.
- Mensagens com links (proibido pelas regras de negócio).

---

## 3. Arquitetura

### 3.1 Diagrama lógico

```
┌───────────────────────────┐                ┌──────────────────────────┐
│  Django API (externa)     │                │  WhatsApp (cliente final)│
│  - /pendentes-recolha/    │                │                          │
│  - /whatsapp-webhook/     │                └─────────────┬────────────┘
└─────────────┬─────────────┘                              │
              │ HTTPS + Token                              │ Baileys
              │                                            │
┌─────────────▼────────────────────────────────────────────▼────────────┐
│                       Docker Compose (host local)                     │
│                                                                       │
│  ┌──────────────┐   ┌─────────────────┐   ┌────────────────────────┐  │
│  │   worker     │◄──┤  evolution-api  │   │  redis (7-alpine)      │  │
│  │  (FastAPI +  │   │  atendai/...    │   │  - filas               │  │
│  │   poller)    │──►│  :8080          │   │  - idempotência evt:*  │  │
│  │  :WORKER_HTTP│   └─────────────────┘   │  - rate-limit bucket   │  │
│  └──────┬───────┘            ▲            └────────────────────────┘  │
│         │                    │                                        │
│         └────────────────────┘  HTTP interno (network compose)        │
└───────────────────────────────────────────────────────────────────────┘
```

### 3.2 Componentes

| Serviço | Imagem | Função |
|---------|--------|--------|
| `evolution-api` | `atendai/evolution-api:latest` | Gateway WhatsApp (Baileys). Expõe API REST e dispara webhooks para o `worker` quando recebe mensagens. |
| `redis` | `redis:7-alpine` | Filas locais, idempotência (`evt:<id>`), rate-limit, estado de conversa curto. |
| `worker` | Build local (`worker/Dockerfile`, `python:3.11-slim`) | Aplicação FastAPI + poller. Lê agendamentos do Django, dispara mensagens via Evolution, recebe webhooks do Evolution e devolve eventos ao Django. |

### 3.3 Stack do worker

- **Python 3.11**
- **FastAPI + Uvicorn** — servidor HTTP que recebe webhooks do Evolution e expõe `/health`.
- **httpx** — cliente HTTP assíncrono para Django e Evolution.
- **pydantic / pydantic-settings** — modelos de dados e carregamento de `.env`.
- **redis (cliente Python)** — filas e idempotência.
- **structlog** — logs JSON estruturados com `correlation_id`.
- **tenacity** — retries com backoff exponencial em chamadas externas.
- **python-dotenv** — fallback para carregamento local fora do Docker.

---

## 4. Fluxos

### 4.1 Fluxo principal — disparo inicial

```
[poller a cada POLLING_INTERVAL_SECONDS]
   │
   ├─► GET /api/logistica-reversa/pendentes-recolha/?page=N
   │   (paginado; itera até esgotar)
   │
   ├─► para cada agendamento:
   │     │
   │     ├─► verifica Redis: já enviado? (chave `sent:<agendamento_id>`)
   │     │   - se sim → skip
   │     │
   │     ├─► aguarda token do bucket de rate-limit (4/min)
   │     │
   │     ├─► monta mensagem de texto com opções numeradas (via build_initial_text)
   │     │   POST {EVOLUTION_API_URL}/message/sendText/{INSTANCE}
   │     │
   │     └─► marca Redis: `sent:<agendamento_id>` TTL 24h
   │
   └─► dorme POLLING_INTERVAL_SECONDS
```

### 4.2 Fluxo reativo — recebimento de webhook

```
[POST /webhook/evolution] (FastAPI)
   │
   ├─► extrai event_id; verifica Redis `evt:<event_id>`
   │   - se já existe → 200 OK e retorna (idempotência)
   │
   ├─► SETNX Redis `evt:<event_id>` TTL 24h
   │
   ├─► classifica resposta:
   │     ├── número "1" ou palavra-chave "confirmar"  → repassa ao Django (CONFIRMAR)
   │     ├── número "2" ou palavra-chave "remarcar"   → busca slots no Django + envia texto numerado de horários
   │     ├── número "3" ou palavra-chave "ja entreguei" → repassa ao Django (JA_ENTREGUE)
   │     ├── número correspondente a horário (ex.: "1", "2" em contexto de slots) → extrai slot do mapping
   │     └── texto livre / inválido → incrementa `errors:<chat_id>`
   │           ├── < 3 → envia fallback + reenvia texto inicial
   │           └── ≥ 3 → marca FALHA no Django e encerra conversa
   │
   └─► POST /api/logistica-reversa/whatsapp-webhook/  (sempre que houver evento canônico)
```

### 4.3 Fluxo de timeout (sem resposta)

- Se um agendamento ficou em estado "aguardando resposta" por X minutos (regra do Django, não do motor), o Django sinaliza via próximo polling. O motor **não controla timeouts próprios** — apenas reage à listagem de pendentes.

---

## 5. Variáveis de Ambiente

Todas obrigatórias salvo indicação contrária. Carregadas em `worker/settings.py` via `pydantic-settings`.

| Variável | Tipo | Default | Descrição |
|----------|------|---------|-----------|
| `DJANGO_API_BASE_URL` | URL | — | Base URL da API Django (ex.: `https://api.dmais.com.br`). Sem barra final. |
| `DJANGO_API_TOKEN` | str | — | Token de autenticação. Enviado como `Authorization: Token <key>`. |
| `EVOLUTION_API_URL` | URL | `http://evolution-api:8080` | URL interna do container EvolutionAPI. |
| `EVOLUTION_API_KEY` | str | — | API key global da EvolutionAPI (header `apikey`). |
| `EVOLUTION_INSTANCE_NAME` | str | `dmais` | Nome da instância (sessão WhatsApp) na Evolution. |
| `REDIS_URL` | URL | `redis://redis:6379/0` | URL de conexão Redis. |
| `POLLING_INTERVAL_SECONDS` | int | `60` | Intervalo entre ciclos de polling. |
| `MAX_MESSAGES_PER_MINUTE` | int | `4` | Capacidade do token bucket de envio (anti-bloqueio WhatsApp). |
| `LOG_LEVEL` | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `WORKER_HTTP_PORT` | int | `8000` | Porta exposta pelo FastAPI do worker. |

---

## 6. Payloads

### 6.1 Mensagem inicial — texto com 3 opções numeradas

**Endpoint Evolution:** `POST {EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}`
**Headers:** `apikey: {EVOLUTION_API_KEY}`, `Content-Type: application/json`

**Payload:**

```json
{
  "number": "55<DDD><numero>",
  "text": "Olá {nome}! Tudo bem?\n\nAqui é da AT3 Internet. Gostaríamos de agendar a visita do técnico para realizar a coleta do equipamento agendada para {DD/MM}.\n\nResponda com o número da opção:\n1 — Confirmar coleta\n2 — Remarcar para outro dia\n3 — Já entreguei"
}
```

> A função `build_initial_text(agendamento)` retorna `(telefone, texto_plano)` — não é um payload JSON de List Message.

### 6.2 Mensagem de horários — texto numerado com até 10 slots

**Endpoint Evolution:** `POST {EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}`
**Headers:** `apikey: {EVOLUTION_API_KEY}`, `Content-Type: application/json`

**Payload (exemplo com seleção de período):**

```json
{
  "number": "55<DDD><numero>",
  "text": "Ótimo! Para Terça, 19/05, qual período seria melhor para a coleta?\n\nResponda com o número da opção:\n1 — Manhã (08:00 às 12:00)\n2 — Tarde (12:00 às 18:00)"
}
```

**Payload (exemplo com slots de horário):**

```json
{
  "number": "55<DDD><numero>",
  "text": "Escolha um dos horários disponíveis respondendo com o número:\n1 — Seg 12/05 às 09h-11h\n2 — Ter 13/05 às 14h-16h"
}
```

> A função `build_horarios_text(agendamento, slots)` retorna `(telefone, texto, mapping)` — onde `mapping` é um dicionário `{número_str: slot_dict}` usado pelo handler `on_response` para resolver qual horário foi escolhido.

> **Regras:** máximo 10 opções numeradas (limite prático por mensagem); o mapping interno mapeia cada número (1–10) ao slot correspondente vindo do Django. O texto legível é formatado a partir de `inicio` e `fim` (ex.: `"Seg 12/05 às 09h-11h"`)

### 6.3 Webhook que o motor envia ao Django

**Endpoint Django:** `POST /api/logistica-reversa/whatsapp-webhook/`
**Headers:** `Authorization: Token {DJANGO_API_TOKEN}`, `Content-Type: application/json`

```json
{
  "event_id": "<evolution event id>",
  "agendamento_id": 123,
  "telefone": "55<DDD><numero>",
  "tipo": "CONFIRMAR | REMARCAR | JA_ENTREGUE | FALHA | RESPOSTA_INVALIDA",
  "slot_escolhido": "2026-05-12T09:00:00-03:00",
  "raw": { "...": "payload bruto recebido do Evolution para auditoria" },
  "correlation_id": "<uuid>"
}
```

### 6.4 Resposta esperada do Django (pendentes-recolha)

`GET /api/logistica-reversa/pendentes-recolha/?page={N}`

```json
{
  "count": 142,
  "next": "https://.../pendentes-recolha/?page=2",
  "previous": null,
  "results": [
    {
      "agendamento_id": 123,
      "nome": "Fulano",
      "telefone": "5511999998888",
      "data": "2026-05-08",
      "hora": "14:00",
      "status": "PENDENTE_CONFIRMACAO"
    }
  ]
}
```

**Valores possíveis de `status`:**

| Valor | Ação do poller |
|---|---|
| `PENDENTE_CONFIRMACAO` | Enviar mensagem inicial (se ainda não enviada) |
| `TIMEOUT` | Chamar `on_timeout.handle(agendamento_id)` e limpar estado Redis |

Qualquer outro valor é ignorado silenciosamente pelo poller.

### 6.5 Resposta esperada do Django (slots de remarcação)

`GET /api/logistica-reversa/slots/{agendamento_id}/`

```json
[
  {
    "slot_id": 1,
    "inicio": "2026-05-12T09:00:00-03:00",
    "fim": "2026-05-12T11:00:00-03:00"
  },
  {
    "slot_id": 2,
    "inicio": "2026-05-13T14:00:00-03:00",
    "fim": "2026-05-13T16:00:00-03:00"
  }
]
```

- Lista vazia `[]` significa sem slots disponíveis → `enviar_slots` deve enviar mensagem neutra e postar `FALHA` ao Django.
- Máximo 10 itens considerados (limite prático por mensagem numerada); itens excedentes são descartados silenciosamente.
- O mapping interno mapeia cada número (1–10) ao slot. O texto legível é formatado a partir de `inicio` e `fim` (ex.: `"Seg 12/05 às 09h-11h"`) pela função `build_horarios_text`.

---

## 7. Idempotência

- **Webhook do Evolution:** chave Redis `evt:<event_id>` com TTL de **24 horas**, definida via `SET key NX EX 86400`. Se já existir, o evento é descartado.
- **Disparo inicial:** chave `sent:<agendamento_id>` TTL 24h evita reenvios em ciclos de polling repetidos.
- **Erros de resposta inválida:** contador `errors:<chat_id>` TTL 24h. Ao atingir 3, envia evento `FALHA` ao Django e zera.

---

## 8. Rate Limiting

- Implementado como **token bucket em Redis** (chaves `ratelimit:bucket` e `ratelimit:last_refill`).
- Capacidade = `MAX_MESSAGES_PER_MINUTE` (default 4 — valor conservador para anti-bloqueio WhatsApp).
- Refill linear (1 token a cada `60/MAX` segundos ≈ 1 a cada 15s).
- Cliente do Evolution chama `acquire()` antes de cada envio; se sem tokens, aguarda assíncrono.

---

## 9. Endpoints expostos pelo worker (FastAPI)

> **Nota:** O motor usa exclusivamente o endpoint `sendText` da EvolutionAPI para todas as mensagens (`/message/sendText/{INSTANCE}`). O endpoint `sendList` **não é utilizado** pois a Meta deprecou List Messages no protocolo Multi-Device.

| Método | Path | Descrição |
|--------|------|-----------|
| `GET`  | `/health` | Healthcheck. Retorna `{"status":"ok","redis":"ok","evolution":"ok"}`. |
| `POST` | `/webhook/evolution` | Recebe webhooks da EvolutionAPI (mensagens, status, conexão). |
| `POST` | `/debug/test-send` | **Apenas para validação de setup.** Dispara o fluxo de envio inicial com um agendamento sintético, sem consultar o Django. Corpo: `{"telefone": "5511999999999", "nome": "Teste", "data": "2026-01-01", "hora": "14:00"}`. Retorna `{"status":"ok","evolution_response":{...}}` ou erro. Usado pelo `make test-send`. |

---

## 10. Logs e Observabilidade

- **Formato:** JSON via `structlog`, escritos em stdout (capturados pelo Docker).
- **Campos obrigatórios:** `timestamp`, `level`, `event`, `correlation_id`, `agendamento_id` (quando aplicável), `telefone` (mascarado: exibir apenas os últimos 4 dígitos, ex.: `"****8888"`).
- **Correlation ID:** gerado no início do polling ou ao receber webhook; propagado em todos os logs do mesmo fluxo via `contextvars`.
- **LGPD:** texto livre digitado pelo cliente nunca deve aparecer em `level=INFO` ou acima. Payloads brutos do Evolution só em `level=DEBUG`. Header `Authorization` deve ser removido pelo processador `structlog` antes de serializar qualquer log.

---

## 11. Critérios de Aceite

1. `docker compose up -d` sobe os 3 serviços com healthcheck `healthy` em até 60 s.
2. Pareamento via QRCode é possível através da rota padrão da EvolutionAPI.
3. Polling busca pendentes do Django e dispara mensagem de texto com opções numeradas sem ultrapassar 4/min.
4. Webhook do Evolution é processado idempotentemente (reenvios não duplicam ações).
5. Resposta `REMARCAR` resulta em mensagem de texto com horários numerados (até 10 slots vindos do Django).
6. Resposta em texto livre dispara fallback; após 3, envia `FALHA` ao Django.
7. Logs em stdout em JSON com `correlation_id` rastreável ponta-a-ponta.
8. Reiniciar containers preserva sessão WhatsApp (volume `evolution-instances` persistido).

---

## 12. Riscos e Mitigações

| Risco | Mitigação |
|-------|-----------|
| Banimento do número WhatsApp por flooding | Token bucket fixo em 4/min (conservador); nunca enviar links. |
| Sessão Baileys quebrar | Volume persistente + healthcheck + reconexão pela EvolutionAPI. |
| Django indisponível | `tenacity` com backoff exponencial; mensagens não são reprocessadas, ficam pendentes para o próximo ciclo. |
| Webhook duplicado do Evolution | Idempotência `evt:<id>` em Redis. |
| Token vazado no log | Filtros no `structlog` removem header `Authorization` antes de serializar. |

---

## 13. Glossário

- **Agendamento:** registro no Django representando uma coleta a ser confirmada.
- **List Message:** tipo de mensagem interativa do WhatsApp com opções clicáveis *(obsoleto — não utilizado; o bot usa texto plano com opções numeradas via `sendText`)*.
- **Instância (Evolution):** sessão Baileys correspondente a um número de WhatsApp pareado.
- **Correlation ID:** UUID que amarra todos os logs de um mesmo fluxo (polling + envio + webhook + repasse).
