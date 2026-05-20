# PROGRESS — dmais_bot_engine (Critérios "Pronto")

> Última atualização: 2026-05-20
> Commit base: `aa6e8fc`

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
- **Status**: Difft pronto, aguardando aprovação
- **Detalhes**:
  - Código JA implementa token bucket (Redis Lua) com `MAX_MESSAGES_PER_MINUTE=4`
  - Jitter JA implementado: `random.uniform(8, 22)` entre mensagens
  - Polling jitter JA implementado: ±20% em `POLLING_INTERVAL_SECONDS`
  - **Falta**: Teste automatizado `worker/tests/test_rate_limit_jitter.py` (diff proposto com 8 testes)
- **Diff proposto** (gerado por subagente):
  - Novo arquivo: `worker/tests/test_rate_limit_jitter.py` (303 linhas, 8 testes)
  - Testes: (a) token bucket respeita 4 msg/min, (b) jitter é random.uniform não fixo, (c) polling ±20% com floor de 1.0s

### 2. ⏳ Polling consome /pendentes-recolha/ paginado
- **Criticidade**: ALTO
- **Branch**: `fix/criterio-polling-paginado`
- **Status**: Subagente interrompido — precisará reexecutar
- **Detalhes**:
  - Código em `worker/main.py` `_poll_loop()` itera páginas via campo `next`
  - `_adapt()` converte agendamento Django → shape do worker
  - Status `PENDENTE_CONTATO` dispara `enviar_inicial.handle()`
  - Status `TIMEOUT` dispara `on_timeout.handle()`
  - **Falta**: Validar com teste automatizado

### 3. ⏱️ Docker compose up saudável com healthchecks
- **Criticidade**: MÉDIO
- **Branch**: `fix/criterio-docker-health`
- **Status**: NÃO iniciado
- **Detalhes**: docker-compose.yml tem 4 serviços (postgres, evolution-api, redis, worker) com healthchecks definidos

### 4. 📖 README permite setup em < 10 min
- **Criticidade**: BAIXO
- **Branch**: `fix/criterio-readme-setup`
- **Status**: NÃO iniciado

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
- Branch `main` está 1 commit à frente de `origin/main` (pendente de `git push`)