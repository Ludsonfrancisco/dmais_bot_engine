# PROGRESS — dmais_bot_engine (Critérios "Pronto")

> Última atualização: 2026-06-10
> Commit mais recente: `6b4ad0d` (docs: atualiza PROGRESS.md com pendencias para terminar mais tarde)
> Fase atual: Report Automation — enviar relatórios/prints do dmais_portal (Backlog/Prazo) para grupo WhatsApp de testes antes de liberar grupo oficial.

---

## Sprint Report Automation — WhatsApp Reports

### Objetivo da fase

Transformar/estender o `dmais_bot_engine` em publicador de relatórios automáticos do `dmais_portal`, com envios por cron para WhatsApp. A base oficial continua sendo o portal; o bot orquestra captura de prints, montagem do texto e envio via EvolutionAPI.

### Regra operacional obrigatória

Nenhum relatório vai direto para o grupo oficial. Todo fluxo começa em `WHATSAPP_TEST_GROUP_JID`; `WHATSAPP_REPORT_GROUP_JID` só é usado depois de homologação explícita.

### Sprints

- **Sprint 0 — Preparação/alinhamento**: corrigir lint/CI, documentar função de relatórios, adicionar variáveis futuras em `.env.example` e validar testes/config.
- **Sprint 1 — Envio seguro para grupo de testes**: envio de texto para grupo WhatsApp com `REPORT_TARGETS=test`.
- **Sprint 2 — Prints do portal**: captura autenticada de `/backlog/` e `/prazo-atendimento/`.
- **Sprint 3 — Envio de imagens**: envio dos prints para o grupo de testes com caption de ambiente.
- **Sprint 4 — Relatórios textuais**: dados atuais do portal, respeitando snapshot mais recente, recálculo de SLA, grupos padrão sem CANCELAMENTO e prioridade de sem técnico.
- **Sprint 5 — Cron scheduler**: jobs com timezone `America/Sao_Paulo`, endpoint de status, proteção contra duplicidade.
- **Sprint 6 — Homologação EasyPanel**: deploy em modo teste com volumes persistentes e WhatsApp pareado.
- **Sprint 7 — Homologação funcional**: ajuste de textos, prints, horários e thresholds no grupo de testes.
- **Sprint 8 — Liberação oficial**: ativação controlada no grupo oficial após aprovação.

### Status Sprint 0

- **Executor responsável**: Hermes Agent
- **Status**: CONCLUÍDO
- **Já validado**:
  - Repo local encontrado em `/home/ludsoncorrea/projetos/dmais_bot_engine`
  - Projeto não está no EasyPanel/Swarm
  - CI GitHub falhava no lint, testes passavam
- **Correções desta Sprint**:
  - Removido `import time` não usado em `worker/tests/test_circuit_breaker.py`
  - Removido alias não usado `mock_set_state` em `worker/tests/test_handler_enviar_slots.py`
  - Documentado Report Automation em `README.md`, `.env.example` e `PROGRESS.md`
- **Validação final**:
  - `.venv/bin/python -m ruff check worker/` → All checks passed!
  - `.venv/bin/python -m pytest worker/tests/ -q` → 107 passed
  - `docker compose --env-file /tmp/dmais_bot_engine.env config --quiet` → passou

---

## Modelo de Delegação por Criticidade

| Criticidade | Modelo | CLI |
|---|---|---|
| Crítico | Opus 4.7 (high effort) | Claude Code (`npx @anthropic-ai/claude-code`) |
| Alto | GPT-5.5 (xhigh) | Codex (`codex`) |
| Médio | GLM-5.1 | OpenCode (`opencode`) — **NÃO instalado**, usar Gemini CLI como fallback |
| Baixo | Gemini 3.5 Flash | Gemini CLI (`gemini`) |

---

## Critérios Globais de "Pronto" — Status

### 1. ⚠️ Rate limit não permite mais de 4 msg/min + sleep randômico
- **Criticidade**: CRÍTICO
- **Branch**: `fix/criterio-rate-limit-test`
- **Status**: CONCLUÍDO E MERGEADO na main
- **Executor responsável**: Subagente + Hermes Agent
- **Validação**: `.venv/bin/python -m pytest worker/tests/test_rate_limit_jitter.py -q` → passou (107 testes no total)
- **Detalhes**:
  - Código JA implementa token bucket (Redis Lua) com `MAX_MESSAGES_PER_MINUTE=4`
  - Jitter JA implementado: `random.uniform(8, 22)` entre mensagens
  - Polling jitter JA implementado: ±20% em `POLLING_INTERVAL_SECONDS`
  - Teste automatizado `worker/tests/test_rate_limit_jitter.py` adicionado

### 2. ⏳ Polling consome /pendentes-recolha/ paginado
- **Criticidade**: ALTO
- **Branch**: `fix/criterio-polling-paginado`
- **Status**: CONCLUÍDO E MERGEADO na main
- **Executor responsável**: Hermes Agent, com revisão delegada
- **Validação**: `.venv/bin/python -m pytest worker/tests/test_polling_pagination.py -q` → passou (107 testes no total)
- **Detalhes**:
  - Código em `worker/main.py` `_poll_loop()` itera páginas via campo `next`
  - `_adapt()` converte agendamento Django → shape do worker
  - Status `PENDENTE_CONTATO` dispara `enviar_inicial.handle()`
  - Status `TIMEOUT` dispara `on_timeout.handle()`
  - Teste automatizado `worker/tests/test_polling_pagination.py` adicionado

### 3. ⏱️ Docker compose up saudável com healthchecks
- **Criticidade**: MÉDIO
- **Branch**: `fix/criterio-docker-health`
- **Status**: CONCLUÍDO E MERGEADO na main
- **Executor responsável**: Hermes Agent, com revisão delegada; Gemini CLI indisponível por falta de autenticação local
- **Validação**: `cp .env.example .env && docker compose config --quiet` → passou
- **Detalhes**:
  - Corrigido `DATABASE_CONNECTION_URI` da EvolutionAPI para usar a senha real do Postgres local
  - Adicionado `POSTGRES_PASSWORD` no `.env.example`
  - Corrigido placeholder inseguro/ambíguo de `EVOLUTION_API_KEY`
  - Healthcheck da EvolutionAPI trocado para comando via Node, evitando depender de `wget` na imagem

### 4. 📖 README permite setup em < 10 min
- **Criticidade**: BAIXO
- **Branch**: `fix/criterio-readme-setup`
- **Status**: CONCLUÍDO E MERGEADO na main
- **Executor responsável**: Hermes Agent, com revisão delegada; Gemini CLI indisponível por falta de autenticação local
- **Validação**: `cp .env.example .env && docker compose config --quiet` → passou; sem placeholders antigos
- **Detalhes**:
  - Setup rápido agora inclui `make up`, `make ps`, `make health`, criação/pareamento da instância e validação do `state=open`
  - Comandos usam variáveis do `.env` em vez de placeholders manuais
  - README corrigido para 4 serviços: postgres, evolution-api, redis, worker

---

## Critérios Já Validados

- [x] Pareamento WhatsApp funcional via QRCode
- [x] Webhook idempotente (testado)
- [x] Texto livre 3x → FALHA ao Django (testado)
- [x] Logs JSON com correlation_id (validado)

---

## Padão Obrigatório para Alterações de Código

1. **Diff antes de aplicar** — o agente mostra a mudança proposta. O usuário aprova antes de seguir.
2. **Explicação curta do porquê** — toda mudança de código vem com justificativa breve.
3. **Teste manual ou automatizado depois** — validar que a mudança fez o que devia.

---

## Notas

- Commit `aa6e8fc` resolveu 5 problemas críticos/altos (PRD, TASKS, DATAS_REMARCAR_DEMO, testes, .env.example, CI/CD)
- Commit `010c30d` adicionou circuit breaker, conversation timeout, e melhorias de resiliencia
- Branch `main` com 4 criterios + melhorias de resiliencia mergeados. Commit e push feitos pelo agente (autorizacao explicita).
- Suíte de testes: 107 passed
- Validação runtime pendente apenas por permissão local no Docker socket (`/var/run/docker.sock`); executar `docker compose up -d --build && docker compose ps` em ambiente com permissão Docker.

---

## Pendencias para Terminar Mais Tarde

### P0 — Validação Docker em ambiente com permissao
- **O que falta**: Executar `docker compose up -d --build` e verificar health de todos os 4 servicos (postgres, evolution-api, redis, worker)
- **Bloqueio atual**: Sem acesso ao Docker socket (`/var/run/docker.sock`) neste ambiente
- **Como validar**: Em maquina com Docker: `docker compose up -d --build && docker compose ps && make health`
- **Risco**: Healthcheck da EvolutionAPI usa comando Node; pode falhar se a imagem nao tiver node instalado

### P1 — CI/CD no GitHub Actions
- **O que falta**: Rodar workflow `.github/workflows/ci.yml` no GitHub e verificar se lint + pytest + docker build passam
- **Bloqueio atual**: Push para origin ainda nao feito (depende de `git push` do usuario)
- **Como validar**: `git push origin main` e acompanhar workflow no GitHub Actions

### P2 — Teste E2E com EvolutionAPI real
- **O que falta**: Validar fluxo completo: parear instancia, enviar mensagem inicial, receber resposta 1/2/3, confirmar/remarcar
- **Bloqueio atual**: Precisa de EvolutionAPI rodando com credentials validas e numero WhatsApp ativo
- **Cenarios a testar**:
  - Fluxo feliz: PENDENTE_CONTATO → confirmar → escolher periodo → AGUARDANDO_COLETA
  - Remarcar: PENDENTE_CONTATO → remarcar → escolher data → escolher periodo → nova coleta agendada
  - Ja entregue: PENDENTE_CONTATO → ja_entregue → confirmar texto → FALHA ao Django
  - Timeout: conversas inativas por 4h → auto-FALHA ao Django
  - Texto livre 3x → FALHA ao Django

### P3 — Integracao com dmais_portal (Django)
- **O que falta**: Validar que webhooks POST/PUT/DELETE para o Django funcionam corretamente
- **Cenarios**:
  - Confirmacao de coleta → Django atualiza status
  - Reagendamento → Django cria nova coleta
  - FALHA → Django registra erro
  - Idempotencia: webhook duplicado nao duplica acao no Django

### P4 — Circuit breaker tuning em producao
- **O que falta**: Ajustar thresholds do circuit breaker com base em metricas reais
- **Valores atuais**: failure_threshold=5, recovery_timeout=900s (15min), max_recovery_timeout=7200s (2h)
- **Monitorar**: Quantas vezes o circuito abre, tempo medio de recovery, falsos positivos

### P5 — Conversation timeout tuning
- **O que falta**: Ajustar `CONVERSATION_TIMEOUT_SECONDS` (atual: 14400s = 4h) com base em dados reais de interacao
- **Monitorar**: Quantas conversas expiram vs convertem, tempo medio de resposta dos usuarios

### P6 — Melhorias futuras candidatas
- Metricas/Observability: adicionar Prometheus/Grafana para metricas do worker (mensagens/min, erros, latencia)
- Retry com backoff para webhooks falhando
- Alerting quando circuit breaker abrir
- Testes de carga para validar rate limit sob concorrencia
