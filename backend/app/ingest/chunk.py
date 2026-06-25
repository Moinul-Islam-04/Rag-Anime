"""Turn normalized AniList records into embeddable chunks + citation metadata.

Slice 1: one chunk per show. The chunk text leads with the title and tags so
proper nouns are present in the embedded text; metadata carries everything the
API needs to cite the source (anime_title + url).
"""


def build_chunk(show: dict) -> dict:
    parts = [show["title"]]
    if show.get("genres"):
        parts.append("Genres: " + ", ".join(show["genres"]))
    if show.get("tags"):
        parts.append("Tags: " + ", ".join(show["tags"]))
    if show.get("synopsis"):
        parts.append("Synopsis: " + show["synopsis"])
    text = "\n".join(parts)

    metadata = {
        "source_type": "anilist",
        "source_url": show.get("url", ""),
        "anime_title": show["title"],
        "mal_id": int(show.get("mal_id") or 0),
        "score": int(show.get("score") or 0),
        "episodes": int(show.get("episodes") or 0),
    }
    chunk_id = f"anilist-{metadata['mal_id'] or show['title']}"
    return {"id": chunk_id, "text": text, "metadata": metadata}


def build_chunks(shows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    chunks: list[dict] = []
    for show in shows:
        chunk = build_chunk(show)
        if chunk["id"] in seen:
            continue
        seen.add(chunk["id"])
        chunks.append(chunk)
    return chunks
