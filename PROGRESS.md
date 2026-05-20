# PROGRESS — dmais_bot_engine (Critérios "Pronto")

> Última atualização: 2026-05-20
> Commit base: `aa6e8fc`
> Integração final local: `main` contém os 4 critérios via merges `90b7558`, `d99b93d`, `b1f5e11`, `855ab22`

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
- **Status**: CONCLUÍDO em branch local — commit `8166db6`
- **Executor responsável**: Subagente + Hermes Agent
- **Validação**: `.venv/bin/python -m pytest worker/tests/test_rate_limit_jitter.py -q` → 10 passed
- **Detalhes**:
  - Código JA implementa token bucket (Redis Lua) com `MAX_MESSAGES_PER_MINUTE=4`
  - Jitter JA implementado: `random.uniform(8, 22)` entre mensagens
  - Polling jitter JA implementado: ±20% em `POLLING_INTERVAL_SECONDS`
  - Teste automatizado `worker/tests/test_rate_limit_jitter.py` adicionado

### 2. ⏳ Polling consome /pendentes-recolha/ paginado
- **Criticidade**: ALTO
- **Branch**: `fix/criterio-polling-paginado`
- **Status**: CONCLUÍDO em branch local — commit `b3a4747`
- **Executor responsável**: Hermes Agent, com revisão delegada
- **Validação**: `.venv/bin/python -m pytest worker/tests/test_polling_pagination.py -q` → 3 passed
- **Detalhes**:
  - Código em `worker/main.py` `_poll_loop()` itera páginas via campo `next`
  - `_adapt()` converte agendamento Django → shape do worker
  - Status `PENDENTE_CONTATO` dispara `enviar_inicial.handle()`
  - Status `TIMEOUT` dispara `on_timeout.handle()`
  - Teste automatizado `worker/tests/test_polling_pagination.py` adicionado

### 3. ⏱️ Docker compose up saudável com healthchecks
- **Criticidade**: MÉDIO
- **Branch**: `fix/criterio-docker-health`
- **Status**: CONCLUÍDO em branch local — commit `781a4b1`
- **Executor responsável**: Hermes Agent, com revisão delegada; Gemini CLI indisponível por falta de autenticação local
- **Validação**: `cp .env.example .env && docker compose config --quiet && git diff --check` → passou
- **Limitação**: `docker compose up -d --build` não pôde ser executado neste ambiente por falta de permissão no socket Docker (`/var/run/docker.sock`)
- **Detalhes**:
  - Corrigido `DATABASE_CONNECTION_URI` da EvolutionAPI para usar a senha real do Postgres local
  - Adicionado `POSTGRES_PASSWORD` no `.env.example`
  - Corrigido placeholder inseguro/ambíguo de `EVOLUTION_API_KEY`
  - Healthcheck da EvolutionAPI trocado para comando via Node, evitando depender de `wget` na imagem

### 4. 📖 README permite setup em < 10 min
- **Criticidade**: BAIXO
- **Branch**: `fix/criterio-readme-setup`
- **Status**: CONCLUÍDO em branch local — commit `114878c`
- **Executor responsável**: Hermes Agent, com revisão delegada; Gemini CLI indisponível por falta de autenticação local
- **Validação**: `cp .env.example .env && docker compose config --quiet && git diff --check` → passou; busca por placeholders antigos (`SUA_API_KEY`, URLs hardcoded dmais, `3 serviços`, `decodifique`) → sem ocorrências
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
- Branch `main` está à frente de `origin/main` e já integra os 4 critérios pendentes. O usuário prefere executar `git push` pessoalmente.
- Validação final integrada: `.venv/bin/python -m pytest worker/tests -q` → 68 passed; `cp .env.example .env && docker compose config --quiet` → passou.
- Validação runtime pendente apenas por permissão local no Docker socket (`/var/run/docker.sock`); executar `docker compose up -d --build && docker compose ps` em ambiente com permissão Docker.