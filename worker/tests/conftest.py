import os

# Must run before any worker.* module is imported (settings = Settings() at module level).
os.environ.setdefault("DJANGO_API_BASE_URL", "https://test.example.com")
os.environ.setdefault("DJANGO_API_TOKEN", "test-token")
os.environ.setdefault("EVOLUTION_API_KEY", "test-key")
os.environ.setdefault("EVOLUTION_INSTANCE_NAME", "test-instance")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
