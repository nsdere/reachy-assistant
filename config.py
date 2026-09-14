import os

from dotenv import load_dotenv

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
ANSWER_MODEL = os.getenv("OLLAMA_ANSWER_MODEL", "qwen2.5:7b")
NOTES_DIR = os.getenv("NOTES_DIR", "/data/sources/notes")

COLLECTION = "personal"
