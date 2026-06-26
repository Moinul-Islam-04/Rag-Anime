"""AniList community recommendation graph — "if you liked X, watch Y" (Phase A).

When a user *names* a show in their query, we surface that show's top
community-recommended in-corpus titles (vote-weighted by AniList users) as
curated candidates, blended into the semantic results in `rag/recommend.py`.

Like `franchise.py` and `meta.py`, this is built from data/anime.json at request
time (`lru_cache(maxsize=1)`) — no vector store involvement, so it needs no
re-embedding. Named-show detection reuses `franchise._aliases`/`_norm` so it
matches the same short forms the no-sequel filter does ("Demon Slayer" ->
"Demon Slayer: Kimetsu no Yaiba").
"""
import json
from functools import lru_cache

from app import config
from app.franchise import _aliases, _norm, franchise_of, representative_of


@lru_cache(maxsize=1)
def _graph() -> dict:
    if not config.ANIME_JSON.exists():
        return {"url_recs": {}, "alias_url": []}
    shows = json.loads(config.ANIME_JSON.read_text())
    url_recs: dict[str, list[dict]] = {}
    alias_url: list[tuple[str, str]] = []
    for show in shows:
        url = show.get("url")
        if not url:
            continue
        recs = show.get("recommendations") or []
        if recs:
            url_recs[url] = recs
        for alias in _aliases(show.get("title", "")):
            alias_url.append((alias, url))
    return {"url_recs": url_recs, "alias_url": alias_url}


def community_recs(url: str) -> list[dict]:
    """In-corpus community recommendations for a show url, sorted votes desc."""
    return _graph()["url_recs"].get(url, [])


def referenced_show_urls(query: str) -> list[str]:
    """Urls of in-corpus shows whose title/alias appears as a whole phrase in the query.

    Unlike `franchise.referenced_franchises` (which returns franchise roots), this
    resolves to the specific show urls so we can look up their recommendations.
    """
    padded = f" {_norm(query)} "
    seen: set[str] = set()
    out: list[str] = []
    for alias, url in _graph()["alias_url"]:
        if url not in seen and f" {alias} " in padded:
            seen.add(url)
            out.append(url)
    return out


def injected_rec_urls(query: str, banned_franchises: set[str], limit: int) -> list[str]:
    """Top community-recommended in-corpus urls for the shows named in the query.

    Drops recs in a franchise the user named (same guard as the no-sequel filter,
    since AniList recs include same-franchise entries) and de-dups. Sorted by votes
    across all named shows, truncated to `limit`.
    """
    pooled: dict[str, int] = {}
    for src_url in referenced_show_urls(query):
        for rec in community_recs(src_url):
            if franchise_of(rec["url"]) in banned_franchises:
                continue  # don't recommend the named show's own franchise
            # Canonicalize a season-specific rec to its franchise flagship and
            # dedupe by franchise (so "Code Geass" + "Code Geass R2" -> one rec,
            # and "AOT Season 3 Part 2" -> "Attack on Titan").
            url = representative_of(rec["url"])
            pooled[url] = max(pooled.get(url, 0), int(rec.get("votes") or 0))
    ranked = sorted(pooled, key=lambda u: pooled[u], reverse=True)
    return ranked[:limit]


def main() -> None:
    import sys

    from app.franchise import referenced_franchises
    from app.meta import get_meta

    q = " ".join(sys.argv[1:]) or "something like Attack on Titan"
    named = referenced_show_urls(q)
    print(f"Query: {q!r}")
    print("Named shows:", [(get_meta(u) or {}).get("title", u) for u in named])
    banned = referenced_franchises(q)
    injected = injected_rec_urls(q, banned, config.COMMUNITY_INJECT_MAX)
    print("Injected community recs:")
    for u in injected:
        print(f"  - {(get_meta(u) or {}).get('title', u)}")


if __name__ == "__main__":
    main()
