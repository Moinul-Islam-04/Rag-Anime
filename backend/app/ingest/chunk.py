"""Turn normalized AniList records into embeddable chunks + citation metadata.

Two chunk kinds per show:
- one **synopsis** chunk (title + genres + tags + synopsis) — plot/proper-noun
  recall. Its id stays `anilist-{mal_id}` so the already-embedded vectors are
  reused on re-ingest (incremental embed skips them).
- N **review** chunks (one per kept AniList review summary) — the experiential /
  comparative vocabulary ("made me cry", "slow burn") that synopses lack, so vibe
  queries become retrievable. Same `source_url` as the synopsis chunk, so citation
  validation and the franchise/show collapse in `rag/recommend.py` still work.
"""
from app import config


def _show_id(show: dict) -> str:
    return f"anilist-{int(show.get('mal_id') or 0) or show['title']}"


def _base_metadata(show: dict) -> dict:
    return {
        "source_type": "anilist",
        "source_url": show.get("url", ""),
        "anime_title": show["title"],
        "mal_id": int(show.get("mal_id") or 0),
        "score": int(show.get("score") or 0),
        "episodes": int(show.get("episodes") or 0),
    }


def build_chunk(show: dict) -> dict:
    """The synopsis chunk (stable id + text — do not change without a --force re-embed)."""
    parts = [show["title"]]
    if show.get("genres"):
        parts.append("Genres: " + ", ".join(show["genres"]))
    if show.get("tags"):
        parts.append("Tags: " + ", ".join(show["tags"]))
    if show.get("synopsis"):
        parts.append("Synopsis: " + show["synopsis"])

    metadata = _base_metadata(show)
    metadata["chunk_type"] = "synopsis"  # NOTE: won't backfill onto already-indexed
    # rows without --force; readers must treat a missing chunk_type as "synopsis".
    return {"id": _show_id(show), "text": "\n".join(parts), "metadata": metadata}


def build_show_chunks(show: dict) -> list[dict]:
    """Synopsis chunk + up to REVIEW_CHUNKS_PER_SHOW review chunks for one show."""
    chunks = [build_chunk(show)]
    base_id = _show_id(show)
    for i, review in enumerate((show.get("reviews") or [])[: config.REVIEW_CHUNKS_PER_SHOW]):
        summary = (review.get("summary") or "").strip()
        if not summary:
            continue
        meta = _base_metadata(show)
        meta["chunk_type"] = "review"
        chunks.append({
            "id": f"{base_id}-rev-{i}",
            "text": f"{show['title']}\nReview: {summary}",
            "metadata": meta,
        })
    return chunks


def build_chunks(shows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    chunks: list[dict] = []
    for show in shows:
        for chunk in build_show_chunks(show):
            if chunk["id"] in seen:
                continue
            seen.add(chunk["id"])
            chunks.append(chunk)
    return chunks
