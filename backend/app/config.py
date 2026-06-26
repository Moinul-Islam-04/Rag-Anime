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

# Retrieval params: dense recall broad (local/cheap), collapse to distinct shows,
# then rerank tight. With multi-chunk retrieval (synopsis + review chunks), the
# dense pool RETRIEVE_K is large for recall, but only RERANK_N *distinct shows*
# are reranked so the Voyage call stays under the free-tier 10K-tokens/min cap.
RETRIEVE_K = 80   # dense chunk candidates pulled from Chroma (local, no Voyage cost)
RERANK_N = 30     # distinct shows reranked by Voyage (TPM-bounded — do not raise blindly)
PROMPT_SHOWS = 12  # distinct shows sent to Claude after the per-franchise collapse

# Phase A — community recommendation graph (AniList `recommendations`).
COMMUNITY_INJECT_MAX = 5   # max curated community recs injected for a named-show query

# Phase B — review-augmented retrieval (AniList `reviews`). Summaries only; the
# enrichment pass stores already-filtered reviews per these bounds.
REVIEW_CHUNKS_PER_SHOW = 3  # cap embedded review summaries per show
REVIEW_MIN_LEN = 20         # drop truncated / one-word summaries
REVIEW_MAX_LEN = 300        # keep summaries short (spoiler + cost control)
REVIEW_MIN_HELPFUL = 2      # min helpful votes — drop troll/low-effort reviews

DATA_DIR.mkdir(parents=True, exist_ok=True)
