# PRD — `dmais_bot_engine` (Motor Local de Disparo WhatsApp)

> **Versão:** 1.0
> **Data:** 2026-05-06
> **Owner:** Equipe DMais — Logística Reversa
> **Status:** Draft (pronto para Sprint C)

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
| O3 | Respeitar limites operacionais do WhatsApp | Nunca ultrapassar 30 msg/min por instância |
| O4 | Operar de forma resiliente sem intervenção manual | Reinício automático de containers; reconexão automática à EvolutionAPI |
| O5 | Ser portável e isolado | `docker compose up` em qualquer host com Docker, sem depender do projeto Django |

### Não-objetivos (Out of Scope)

- Persistir histórico de mensagens (responsabilidade do Django).
- Enviar mídias (imagens, áudios, documentos) — apenas List Messages textuais.
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
   │     ├─► aguarda token do bucket de rate-limit (30/min)
   │     │
   │     ├─► monta payload List Message inicial (3 opções)
   │     │   POST {EVOLUTION_API_URL}/message/sendList/{INSTANCE}
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
   │     ├── opção CONFIRMAR  → repassa ao Django
   │     ├── opção REMARCAR   → busca slots no Django + envia List de horários
   │     ├── opção JA_ENTREGUE → repassa ao Django
   │     └── texto livre / inválido → incrementa `errors:<chat_id>`
   │           ├── < 3 → envia fallback + reenvia List inicial
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
| `MAX_MESSAGES_PER_MINUTE` | int | `30` | Capacidade do token bucket de envio. |
| `LOG_LEVEL` | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `WORKER_HTTP_PORT` | int | `8000` | Porta exposta pelo FastAPI do worker. |

---

## 6. Payloads

### 6.1 List Message inicial — 3 opções

**Endpoint Evolution:** `POST {EVOLUTION_API_URL}/message/sendList/{EVOLUTION_INSTANCE_NAME}`
**Headers:** `apikey: {EVOLUTION_API_KEY}`, `Content-Type: application/json`

```json
{
  "number": "55<DDD><numero>",
  "title": "Confirmação de Coleta",
  "description": "Olá {nome}! Sua coleta está agendada para {data} às {hora}. O que deseja fazer?",
  "buttonText": "Selecionar opção",
  "footerText": "DMais Logística Reversa",
  "sections": [
    {
      "title": "Opções",
      "rows": [
        { "rowId": "CONFIRMAR",   "title": "Confirmar coleta",         "description": "Mantém o horário agendado" },
        { "rowId": "REMARCAR",    "title": "Remarcar para outro dia",  "description": "Escolher novo horário"     },
        { "rowId": "JA_ENTREGUE", "title": "Já entreguei",             "description": "Produto já foi devolvido"  }
      ]
    }
  ]
}
```

### 6.2 List Message de horários — até 10 slots

```json
{
  "number": "55<DDD><numero>",
  "title": "Escolha um novo horário",
  "description": "Selecione um dos horários disponíveis abaixo:",
  "buttonText": "Ver horários",
  "footerText": "DMais Logística Reversa",
  "sections": [
    {
      "title": "Horários disponíveis",
      "rows": [
        { "rowId": "SLOT:<iso8601>", "title": "Seg 12/05 às 09h-11h", "description": "" }
      ]
    }
  ]
}
```

> **Regras:** máximo 10 `rows` por seção (limite do WhatsApp); `rowId` deve ser um identificador parseável do tipo `SLOT:<iso8601>` para o motor extrair o horário escolhido.

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

---

## 7. Idempotência

- **Webhook do Evolution:** chave Redis `evt:<event_id>` com TTL de **24 horas**, definida via `SET key NX EX 86400`. Se já existir, o evento é descartado.
- **Disparo inicial:** chave `sent:<agendamento_id>` TTL 24h evita reenvios em ciclos de polling repetidos.
- **Erros de resposta inválida:** contador `errors:<chat_id>` TTL 24h. Ao atingir 3, envia evento `FALHA` ao Django e zera.

---

## 8. Rate Limiting

- Implementado como **token bucket em Redis** (chaves `ratelimit:bucket` e `ratelimit:last_refill`).
- Capacidade = `MAX_MESSAGES_PER_MINUTE` (default 30).
- Refill linear (1 token a cada `60/MAX` segundos).
- Cliente do Evolution chama `acquire()` antes de cada envio; se sem tokens, aguarda assíncrono.

---

## 9. Endpoints expostos pelo worker (FastAPI)

| Método | Path | Descrição |
|--------|------|-----------|
| `GET`  | `/health` | Healthcheck. Retorna `{"status":"ok","redis":"ok","evolution":"ok"}`. |
| `POST` | `/webhook/evolution` | Recebe webhooks da EvolutionAPI (mensagens, status, conexão). |

---

## 10. Logs e Observabilidade

- **Formato:** JSON via `structlog`, escritos em stdout (capturados pelo Docker).
- **Campos obrigatórios:** `timestamp`, `level`, `event`, `correlation_id`, `agendamento_id` (quando aplicável), `telefone` (mascarado nos últimos 4 dígitos).
- **Correlation ID:** gerado no início do polling ou ao receber webhook; propagado em todos os logs do mesmo fluxo via `contextvars`.
- **LGPD:** mensagens não devem logar conteúdo livre digitado pelo cliente em `level=INFO`; usar `DEBUG` para payloads brutos.

---

## 11. Critérios de Aceite

1. `docker compose up -d` sobe os 3 serviços com healthcheck `healthy` em até 60 s.
2. Pareamento via QRCode é possível através da rota padrão da EvolutionAPI.
3. Polling busca pendentes do Django e dispara List Message inicial sem ultrapassar 30/min.
4. Webhook do Evolution é processado idempotentemente (reenvios não duplicam ações).
5. Resposta `REMARCAR` resulta em segunda List com até 10 slots vindos do Django.
6. Resposta em texto livre dispara fallback; após 3, envia `FALHA` ao Django.
7. Logs em stdout em JSON com `correlation_id` rastreável ponta-a-ponta.
8. Reiniciar containers preserva sessão WhatsApp (volume `evolution-instances` persistido).

---

## 12. Riscos e Mitigações

| Risco | Mitigação |
|-------|-----------|
| Banimento do número WhatsApp por flooding | Token bucket fixo em 30/min; nunca enviar links. |
| Sessão Baileys quebrar | Volume persistente + healthcheck + reconexão pela EvolutionAPI. |
| Django indisponível | `tenacity` com backoff exponencial; mensagens não são reprocessadas, ficam pendentes para o próximo ciclo. |
| Webhook duplicado do Evolution | Idempotência `evt:<id>` em Redis. |
| Token vazado no log | Filtros no `structlog` removem header `Authorization` antes de serializar. |

---

## 13. Glossário

- **Agendamento:** registro no Django representando uma coleta a ser confirmada.
- **List Message:** tipo de mensagem interativa do WhatsApp com opções clicáveis.
- **Instância (Evolution):** sessão Baileys correspondente a um número de WhatsApp pareado.
- **Correlation ID:** UUID que amarra todos os logs de um mesmo fluxo (polling + envio + webhook + repasse).
