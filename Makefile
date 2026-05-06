# =============================================================================
# dmais_bot_engine — Makefile
# =============================================================================
# Atalhos para operações comuns do Docker Compose.
# Uso: make <comando>
# =============================================================================

.PHONY: up down logs restart build test-send qrcode health shell-worker shell-redis ps

# ---------------------------------------------------------------------------
# Subir todos os serviços (rebuild automático)
# ---------------------------------------------------------------------------
up:
	docker compose up -d --build

# ---------------------------------------------------------------------------
# Parar e remover containers (volumes preservados)
# ---------------------------------------------------------------------------
down:
	docker compose down

# ---------------------------------------------------------------------------
# Ver logs em tempo real (últimas 200 linhas)
# ---------------------------------------------------------------------------
logs:
	docker compose logs -f --tail=200

# ---------------------------------------------------------------------------
# Logs apenas do worker
# ---------------------------------------------------------------------------
logs-worker:
	docker compose logs -f --tail=200 worker

# ---------------------------------------------------------------------------
# Reiniciar apenas o worker (útil após mudanças de código)
# ---------------------------------------------------------------------------
restart:
	docker compose restart worker

# ---------------------------------------------------------------------------
# Rebuild completo sem cache
# ---------------------------------------------------------------------------
build:
	docker compose build --no-cache

# ---------------------------------------------------------------------------
# Verificar status dos containers e healthchecks
# ---------------------------------------------------------------------------
ps:
	docker compose ps

# ---------------------------------------------------------------------------
# Health check manual do worker
# ---------------------------------------------------------------------------
health:
	@curl -s http://localhost:$${WORKER_HTTP_PORT:-8000}/health | python -m json.tool

# ---------------------------------------------------------------------------
# Abrir shell no container do worker
# ---------------------------------------------------------------------------
shell-worker:
	docker compose exec worker /bin/bash

# ---------------------------------------------------------------------------
# Abrir shell no Redis (redis-cli)
# ---------------------------------------------------------------------------
shell-redis:
	docker compose exec redis redis-cli

# ---------------------------------------------------------------------------
# QRCode — Obter QR de pareamento da instância EvolutionAPI
# ---------------------------------------------------------------------------
qrcode:
	@echo "Buscando QRCode da instância '$${EVOLUTION_INSTANCE_NAME:-dmais}'..."
	@curl -s -X GET \
		"http://localhost:8080/instance/connect/$${EVOLUTION_INSTANCE_NAME:-dmais}" \
		-H "apikey: $${EVOLUTION_API_KEY}" | python -m json.tool

# ---------------------------------------------------------------------------
# Envio de teste — Dispara um agendamento fake para validar setup
# ---------------------------------------------------------------------------
test-send:
	@echo "Enviando mensagem de teste via worker..."
	@curl -s -X POST \
		"http://localhost:$${WORKER_HTTP_PORT:-8000}/debug/test-send" \
		-H "Content-Type: application/json" \
		-d '{"telefone":"5511999999999","nome":"Teste","data":"2026-01-01","hora":"14:00"}' \
		| python -m json.tool

# ---------------------------------------------------------------------------
# Limpar TUDO (containers + volumes) — CUIDADO: perde sessão WhatsApp
# ---------------------------------------------------------------------------
clean:
	@echo "⚠️  Isso vai apagar todos os volumes (sessão WhatsApp, dados Redis)!"
	@read -p "Tem certeza? [y/N] " confirm && [ "$$confirm" = "y" ] && \
		docker compose down -v || echo "Cancelado."
