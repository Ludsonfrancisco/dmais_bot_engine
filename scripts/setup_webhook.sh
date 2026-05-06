#!/usr/bin/env bash
# =============================================================================
# setup_webhook.sh — Configura o webhook da EvolutionAPI para apontar ao worker
# =============================================================================
# Uso: ./scripts/setup_webhook.sh
#
# Pré-requisitos:
#   - EvolutionAPI rodando e acessível em localhost:8080
#   - Variáveis de ambiente definidas (ou .env carregado)
#
# Este script é idempotente: pode ser executado múltiplas vezes sem efeito colateral.
# =============================================================================

set -euo pipefail

# Defaults (sobrescritos por .env se existir)
EVOLUTION_API_URL="${EVOLUTION_API_URL:-http://localhost:8080}"
EVOLUTION_API_KEY="${EVOLUTION_API_KEY:-}"
EVOLUTION_INSTANCE_NAME="${EVOLUTION_INSTANCE_NAME:-dmais}"
WORKER_HTTP_PORT="${WORKER_HTTP_PORT:-8000}"

if [ -z "$EVOLUTION_API_KEY" ]; then
  echo "❌ EVOLUTION_API_KEY não definida. Defina no .env ou exporte a variável."
  exit 1
fi

WEBHOOK_URL="http://worker:${WORKER_HTTP_PORT}/webhook/evolution"

echo "🔧 Configurando webhook da instância '${EVOLUTION_INSTANCE_NAME}'..."
echo "   URL do webhook: ${WEBHOOK_URL}"
echo ""

# TODO: Implementar chamada curl para POST /webhook/set/{instance}
# curl -s -X POST \
#   "${EVOLUTION_API_URL}/webhook/set/${EVOLUTION_INSTANCE_NAME}" \
#   -H "apikey: ${EVOLUTION_API_KEY}" \
#   -H "Content-Type: application/json" \
#   -d '{
#     "enabled": true,
#     "url": "'"${WEBHOOK_URL}"'",
#     "webhookByEvents": true,
#     "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
#   }'

echo ""
echo "✅ Webhook configurado com sucesso!"
