"""Central config: paths, model ids, retrieval params, and API keys.

Keys are loaded from backend/.env via python-dotenv. The Voyage and Anthropic
SDK clients are constructed with explicit keys (see services.py) so a missing
shell env var doesn't silently fall back to the wrong account.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
ANIME_JSON = DATA_DIR / "anime.json"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "app.db"  # SQLite: user query history

load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")

# Models
EMBED_MODEL = "voyage-3.5"
RERANK_MODEL = "rerank-2.5"
GEN_MODEL = "claude-sonnet-4-6"

# Vector store
COLLECTION = "anime"

# Retrieval params: retrieve broad with dense vectors, then rerank tight.
RETRIEVE_K = 30   # dense candidates pulled from Chroma
RERANK_N = 10     # candidates kept after Voyage rerank (pool the LLM draws cited recs from)

DATA_DIR.mkdir(parents=True, exist_ok=True)
