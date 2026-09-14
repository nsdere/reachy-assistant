from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # "base" is the sweet spot on this CPU: ~1 GB RAM, a few seconds per question.
    # "small" is noticeably more accurate and roughly twice as slow.
    whisper_model: str = "base"
    whisper_compute: str = "int8"

    # Empty means auto-detect, which handles switching languages mid-day at the
    # cost of occasionally guessing wrong on a very short question. Pin it
    # ("en", "tr") if you always speak the same language.
    whisper_language: str = ""

    piper_voice: str = "en_US-lessac-medium"
    models_dir: str = "/models"


settings = Settings()
