"""Embed chunks with Voyage and upsert them into the persistent Chroma collection.

Usage:
    python -m app.ingest.embed_index           # incremental: only embed new chunk ids
    python -m app.ingest.embed_index --force    # re-embed everything

Incremental by default: existing chunk ids are skipped, so growing the corpus
(bump `anilist --target`, re-run this) only spends Voyage tokens on new titles.
"""
import argparse
import json
import sys

from app import config
from app.ingest.chunk import build_chunks
from app.services import chroma_collection, voyage_embed

# Small batches keep each call under the free-tier 10K tokens/min cap.
EMBED_BATCH = 16


def _embed_and_upsert(collection, todo: list[dict]) -> None:
    """Embed + upsert one batch at a time so progress persists — a long free-tier
    run that gets interrupted can be re-run and resumes (incremental skip)."""
    for i in range(0, len(todo), EMBED_BATCH):
        batch = todo[i : i + EMBED_BATCH]
        vectors = voyage_embed([c["text"] for c in batch], input_type="document")
        collection.upsert(
            ids=[c["id"] for c in batch],
            embeddings=vectors,
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        print(f"  embedded+upserted {min(i + EMBED_BATCH, len(todo))}/{len(todo)}", flush=True)


def _existing_ids(collection) -> set[str]:
    try:
        return set(collection.get(include=[])["ids"])
    except Exception:
        return set()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-embed all chunks")
    args = parser.parse_args()

    if not config.ANIME_JSON.exists():
        sys.exit("data/anime.json not found. Run: python -m app.ingest.anilist")

    shows = json.loads(config.ANIME_JSON.read_text())
    chunks = build_chunks(shows)
    if not chunks:
        sys.exit("No chunks built from anime.json.")

    collection = chroma_collection()
    have = set() if args.force else _existing_ids(collection)
    todo = [c for c in chunks if c["id"] not in have]
    print(f"{len(chunks)} chunks total; {len(have)} already indexed; {len(todo)} to embed.", flush=True)
    if not todo:
        print("Nothing new to embed.")
        return

    print(f"Embedding {len(todo)} chunks with {config.EMBED_MODEL} ...", flush=True)
    _embed_and_upsert(collection, todo)
    print(f"Indexed {collection.count()} chunks in Chroma collection '{config.COLLECTION}'.")


if __name__ == "__main__":
    main()
