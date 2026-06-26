"""Enrich data/anime.json with AniList `recommendations` + `reviews`, in place.

Why a separate pass (not folded into ingest/anilist.py): AniList enforces a
per-request query-complexity budget (~500). Nesting two paginated connections
(`recommendations`, `reviews`) inside the 50-media popularity page blows past it,
so we enrich one show per request keyed by `idMal` (complexity ~80-120).

Adds two keys per show (both consumed downstream via `.get`, so older records
stay valid):
- `recommendations`: [{"url", "votes"}] — community "if you liked X, watch Y",
  vote-weighted, filtered to IN-CORPUS shows only (Phase A injection).
- `reviews`: [{"summary", "score", "helpful"}] — short, quality/spoiler-filtered
  opinion lines embedded as extra chunks (Phase B review-augmented retrieval).

Merge-in-place + idempotent. NOTE: re-running `python -m app.ingest.anilist`
overwrites anime.json and drops this enrichment — re-run this pass afterward.

Usage:
    python -m app.ingest.anilist_enrich
    python -m app.ingest.anilist_enrich --limit 20   # smoke test on first N shows
"""
import argparse
import json
import sys
import time

import httpx

from app import config

ANILIST_URL = "https://graphql.anilist.co"

QUERY = """
query ($idMal: Int) {
  Media(idMal: $idMal, type: ANIME) {
    idMal
    recommendations(sort: RATING_DESC, perPage: 15) {
      edges { node { rating mediaRecommendation { idMal siteUrl } } }
    }
    reviews(sort: RATING_DESC, perPage: 6) {
      nodes { summary score rating ratingAmount }
    }
  }
}
"""

# Conservative — only nuke summaries that advertise spoilers; keep emotional ones.
_SPOILER_MARKERS = ("spoiler", "the ending", "who dies", " dies at", "plot twist reveal")


def _clean_recommendations(media: dict, mal_to_url: dict[int, str]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for edge in ((media.get("recommendations") or {}).get("edges") or []):
        node = edge.get("node") or {}
        rec = node.get("mediaRecommendation") or {}
        rmal = rec.get("idMal")
        url = mal_to_url.get(rmal)  # keep ONLY in-corpus recs, keyed to corpus url
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "votes": int(node.get("rating") or 0)})
    out.sort(key=lambda r: r["votes"], reverse=True)
    return out


def _clean_reviews(media: dict) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for node in ((media.get("reviews") or {}).get("nodes") or []):
        summary = (node.get("summary") or "").strip()
        helpful = int(node.get("rating") or 0)
        low = summary.lower()
        if not (config.REVIEW_MIN_LEN <= len(summary) <= config.REVIEW_MAX_LEN):
            continue
        if helpful < config.REVIEW_MIN_HELPFUL:
            continue
        if any(m in low for m in _SPOILER_MARKERS):
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append({"summary": summary, "score": int(node.get("score") or 0), "helpful": helpful})
        if len(out) >= config.REVIEW_CHUNKS_PER_SHOW:
            break
    return out


def _fetch(client: httpx.Client, id_mal: int) -> dict | None:
    """One show's enrichment payload, with the same 429/Retry-After loop as ingest."""
    while True:
        resp = client.post(ANILIST_URL, json={"query": QUERY, "variables": {"idMal": id_mal}})
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return (resp.json().get("data") or {}).get("Media")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="only enrich first N shows (smoke test)")
    args = parser.parse_args()

    if not config.ANIME_JSON.exists():
        sys.exit("data/anime.json not found. Run: python -m app.ingest.anilist")

    shows = json.loads(config.ANIME_JSON.read_text())
    mal_to_url = {int(s["mal_id"]): s["url"] for s in shows if s.get("mal_id") and s.get("url")}

    targets = [s for s in shows if s.get("mal_id")]
    if args.limit:
        targets = targets[: args.limit]

    n_rec = n_rev = 0
    with httpx.Client(timeout=30) as client:
        for i, show in enumerate(targets, 1):
            try:
                media = _fetch(client, int(show["mal_id"]))
            except httpx.HTTPError as e:
                print(f"  [{i}/{len(targets)}] {show['title']}: fetch failed ({e})", file=sys.stderr)
                time.sleep(1.0)
                continue
            if media:
                show["recommendations"] = _clean_recommendations(media, mal_to_url)
                show["reviews"] = _clean_reviews(media)
                n_rec += bool(show["recommendations"])
                n_rev += bool(show["reviews"])
            if i % 50 == 0:
                print(f"  {i}/{len(targets)} enriched (recs:{n_rec} reviews:{n_rev})")
            time.sleep(2.0)  # AniList's degraded limit is ~30 req/min; 2s steady
            # pacing avoids the 60s Retry-After penalties that burstier pacing trips.

    config.ANIME_JSON.write_text(json.dumps(shows, ensure_ascii=False, indent=2))
    print(f"Enriched {len(targets)} shows -> {config.ANIME_JSON}")
    print(f"  with >=1 in-corpus recommendation: {n_rec}")
    print(f"  with >=1 kept review:              {n_rev}")


if __name__ == "__main__":
    main()
