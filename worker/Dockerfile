# =============================================================================
# dmais_bot_engine — Worker Dockerfile
# =============================================================================
# Imagem leve baseada em python:3.11-slim
# Roda FastAPI + Uvicorn como usuário não-root
# =============================================================================

FROM python:3.11-slim AS base

# Metadados
LABEL maintainer="Equipe DMais"
LABEL description="Worker do motor de disparo WhatsApp — dmais_bot_engine"

# Variáveis de build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema (curl + Chromium deps para Playwright)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libnss3 \
        libnspr4 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primeiro (cache de layer do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Instalar navegador Chromium para Playwright (root, antes do USER)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Copiar código do worker como pacote Python (worker.main:app)
COPY . ./worker/

# Criar usuário não-root para segurança
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash appuser && \
    chown -R appuser:appuser /app


USER appuser

# Porta exposta (documentação; o valor real vem do compose)
EXPOSE 8000

# Comando de inicialização
CMD ["uvicorn", "worker.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
