# =============================================================================
# dmais_bot_engine — Makefile
# =============================================================================
# Atalhos para operações comuns do Docker Compose.
# Uso: make <comando>
# =============================================================================

# Carrega .env automaticamente para que EVOLUTION_API_KEY etc. estejam disponíveis
-include .env
export

.PHONY: up down logs restart build test-send qrcode health shell-worker shell-redis ps test demo

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
	@curl -s http://localhost:$${WORKER_HTTP_PORT:-8000}/health | python3 -m json.tool

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
	@echo "Buscando QRCode da instância '$(EVOLUTION_INSTANCE_NAME)'..."
	@curl -s -X GET \
		"http://localhost:8080/instance/connect/$(EVOLUTION_INSTANCE_NAME)" \
		-H "apikey: $(EVOLUTION_API_KEY)" | python3 -c "\
import sys, json, base64, os; \
d = json.load(sys.stdin); \
state = d.get('instance',{}).get('state') or ('open' if d.get('me') else None); \
qr = d.get('qrcode') or d; \
base64_data = qr.get('base64',''); \
code = qr.get('code',''); \
count = qr.get('count',0); \
print('---'); \
print('Estado:', state or 'connecting'); \
print('QR count:', count); \
print('QR disponível:', 'SIM' if code else 'NÃO'); \
(\
  open('/tmp/dmais_qr.png','wb').write(base64.b64decode(base64_data.split(',')[1])) \
  and print('QR salvo em: /tmp/dmais_qr.png (abra para escanear)') \
) if base64_data else None; \
print('---'); \
"

# ---------------------------------------------------------------------------
# Envio de teste — Dispara um agendamento fake para validar setup
# ---------------------------------------------------------------------------
test-send:
	@echo "Enviando mensagem de teste via worker..."
	@curl -s -X POST \
		"http://localhost:$${WORKER_HTTP_PORT:-8000}/debug/test-send" \
		-H "Content-Type: application/json" \
		-d '{"telefone":"5511999999999","nome":"Teste","data":"2026-01-01","hora":"14:00"}' \
		| python3 -m json.tool

# ---------------------------------------------------------------------------
# Rodar testes unitários dentro do container worker
# ---------------------------------------------------------------------------
test:
	docker compose exec worker python -m pytest tests/ -v

# ---------------------------------------------------------------------------
# Demo end-to-end — sobe stack, aguarda healthcheck e dispara mensagem de teste
# Você verá os logs JSON com correlation_id, telefone mascarado e resposta da Evolution
# ---------------------------------------------------------------------------
demo:
	@echo "=== [1/3] Subindo stack... ==="
	@docker compose up -d --build
	@echo "=== [2/3] Aguardando worker ficar healthy (max 90s)... ==="
	@timeout 90 sh -c 'until docker compose exec worker curl -sf http://localhost:8000/health > /dev/null 2>&1; do sleep 3; done' \
		|| (echo "ERRO: worker nao ficou healthy. Verifique: make ps && make logs" && exit 1)
	@echo "=== [3/3] Stack pronta! Disparando mensagem de teste... ==="
	@make test-send
	@echo ""
	@echo "=== Logs em tempo real (Ctrl+C para sair) ==="
	@make logs-worker

# ---------------------------------------------------------------------------
# Limpar TUDO (containers + volumes) — CUIDADO: perde sessão WhatsApp
# ---------------------------------------------------------------------------
clean:
	@echo "⚠️  Isso vai apagar todos os volumes (sessão WhatsApp, dados Redis)!"
	@read -p "Tem certeza? [y/N] " confirm && [ "$$confirm" = "y" ] && \
		docker compose down -v || echo "Cancelado."
