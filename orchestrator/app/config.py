from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    qdrant_url: str = "http://qdrant:6333"
    ollama_url: str = "http://ollama:11434"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    cloud_model: str = "claude-haiku-4-5"

    # "Mando live". LIVE_URL is overridable because the endpoint spelling is the
    # one thing in app/live.py worth double-checking against the current docs.
    live_url: str = "wss://api.openai.com/v1/live/sessions"
    live_model: str = "gpt-live-1"
    live_voice: str = "marin"
    live_delegate_model: str = "gpt-5.6-terra"
    live_idle_seconds: int = 25
    live_cost_per_minute: float = 0.05
    local_model: str = "qwen3:1.7b"
    embed_model: str = "nomic-embed-text"

    daily_budget_usd: float = 1.00
    budget_file: str = "/data/budget.json"
    memory_file: str = "/data/memory.db"

    inbox_dir: str = "/data/inbox"
    ingest_file: str = "/data/ingest.db"


settings = Settings()
