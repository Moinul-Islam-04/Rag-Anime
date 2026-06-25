"""Embed chunks with Voyage and upsert them into the persistent Chroma collection.

Usage:
    python -m app.ingest.embed_index

Re-runnable: upsert is idempotent on chunk id.
"""
import json
import sys

from app import config
from app.ingest.chunk import build_chunks
from app.services import chroma_collection, voyage_embed

# Small batches keep each call under the free-tier 10K tokens/min cap.
EMBED_BATCH = 16


def embed_documents(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        vectors.extend(voyage_embed(batch, input_type="document"))
        print(f"  embedded {min(i + EMBED_BATCH, len(texts))}/{len(texts)}")
    return vectors


def main() -> None:
    if not config.ANIME_JSON.exists():
        sys.exit("data/anime.json not found. Run: python -m app.ingest.anilist")

    shows = json.loads(config.ANIME_JSON.read_text())
    chunks = build_chunks(shows)
    if not chunks:
        sys.exit("No chunks built from anime.json.")

    print(f"Embedding {len(chunks)} chunks with {config.EMBED_MODEL} ...")
    vectors = embed_documents([c["text"] for c in chunks])

    collection = chroma_collection()
    collection.upsert(
        ids=[c["id"] for c in chunks],
        embeddings=vectors,
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    print(f"Indexed {collection.count()} chunks in Chroma collection '{config.COLLECTION}'.")


if __name__ == "__main__":
    main()
