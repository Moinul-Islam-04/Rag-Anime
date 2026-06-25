"""Lazily-constructed shared clients (Voyage, Anthropic, Chroma).

Constructed on first use so importing a module (e.g. for the ingestion CLI)
doesn't require every key to be present.

Voyage calls go through throttled, rate-limit-retrying wrappers so the project
works on the Voyage free tier (3 RPM / 10K TPM without a payment method).
Set VOYAGE_MIN_INTERVAL=0 once you've raised your Voyage limits to remove the
client-side throttle.
"""
import os
import time
from collections import OrderedDict
from functools import lru_cache

from app import config

# Seconds to space consecutive Voyage calls. ~21s keeps us under 3 RPM.
VOYAGE_MIN_INTERVAL = float(os.getenv("VOYAGE_MIN_INTERVAL", "21"))
_last_voyage_call = 0.0

# In-memory LRU cache of embeddings, keyed by (input_type, text). Repeated
# queries (example chips, retries, shared /?q= deep-links) skip the Voyage call.
_EMBED_CACHE_MAX = 512
_embed_cache: "OrderedDict[tuple[str, str], list[float]]" = OrderedDict()


@lru_cache(maxsize=1)
def voyage():
    import voyageai

    if not config.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY is not set (backend/.env).")
    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


def _voyage_call(fn, *args, **kwargs):
    """Throttle + retry a Voyage SDK call against free-tier rate limits."""
    import voyageai.error

    global _last_voyage_call
    for attempt in range(6):
        wait = VOYAGE_MIN_INTERVAL - (time.time() - _last_voyage_call)
        if wait > 0:
            time.sleep(wait)
        try:
            result = fn(*args, **kwargs)
            _last_voyage_call = time.time()
            return result
        except voyageai.error.RateLimitError:
            _last_voyage_call = time.time()
            backoff = 35
            print(f"  voyage rate-limited; sleeping {backoff}s (attempt {attempt + 1}/6)")
            time.sleep(backoff)
    raise RuntimeError(
        "Voyage rate limit exhausted after retries. Add a payment method to raise "
        "limits (free tokens still apply), or wait and retry."
    )


def voyage_embed(texts: list[str], input_type: str) -> list[list[float]]:
    """Embed texts, serving cache hits locally and calling Voyage only for misses."""
    results: list[list[float] | None] = [None] * len(texts)
    miss_texts: list[str] = []
    miss_idx: list[int] = []
    for i, text in enumerate(texts):
        key = (input_type, text)
        cached = _embed_cache.get(key)
        if cached is not None:
            _embed_cache.move_to_end(key)
            results[i] = cached
        else:
            miss_texts.append(text)
            miss_idx.append(i)

    if miss_texts:
        res = _voyage_call(
            voyage().embed, miss_texts, model=config.EMBED_MODEL, input_type=input_type
        )
        for idx, vec in zip(miss_idx, res.embeddings):
            results[idx] = vec
            key = (input_type, texts[idx])
            _embed_cache[key] = vec
            _embed_cache.move_to_end(key)
            while len(_embed_cache) > _EMBED_CACHE_MAX:
                _embed_cache.popitem(last=False)

    return results  # type: ignore[return-value]


def voyage_rerank(query: str, documents: list[str], top_k: int):
    res = _voyage_call(
        voyage().rerank, query, documents, model=config.RERANK_MODEL, top_k=top_k
    )
    return res.results


@lru_cache(maxsize=1)
def anthropic_client():
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (backend/.env).")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


@lru_cache(maxsize=1)
def chroma_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    # cosine space matches Voyage embeddings; we supply vectors ourselves.
    return client.get_or_create_collection(
        name=config.COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
