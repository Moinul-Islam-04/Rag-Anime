"""Lookup of full anime metadata (cover, year, streaming, genres) by source URL.

Built from data/anime.json so the recommendation API can attach rich display
metadata to each cited source without re-querying AniList. Loaded once per
process; the dev server reload re-reads it after a re-ingest.
"""
import json
from functools import lru_cache

from app import config


@lru_cache(maxsize=1)
def _by_url() -> dict[str, dict]:
    if not config.ANIME_JSON.exists():
        return {}
    data = json.loads(config.ANIME_JSON.read_text())
    return {rec["url"]: rec for rec in data if rec.get("url")}


def get_meta(url: str) -> dict | None:
    return _by_url().get(url)
