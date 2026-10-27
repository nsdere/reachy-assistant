from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    qdrant_url: str = "http://qdrant:6333"
    ollama_url: str = "http://ollama:11434"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    # "Hey Mando". cloud_provider is "openai" or "anthropic"; the per-million
    # token prices feed the daily budget, so keep them in step with cloud_model.
    cloud_provider: str = "anthropic"
    cloud_model: str = "claude-haiku-4-5"
    cloud_reasoning_effort: str = "low"
    cloud_input_per_mtok: float = 1.0
    cloud_output_per_mtok: float = 5.0

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
