"""
worker.settings
===============
Carregamento e validação de variáveis de ambiente via pydantic-settings.

Referência: PRD.md §5 — Variáveis de Ambiente.

Uso:
    from worker.settings import settings
    print(settings.DJANGO_API_BASE_URL)
"""

# TODO: Implementar na task 10.C.9
# - Classe Settings(BaseSettings) com todas as variáveis do PRD §5
# - Validações de tipo (URLs, inteiros positivos, log level enum)
# - model_config com env_file=".env"
# - Singleton: settings = Settings()
