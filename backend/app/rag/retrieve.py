"""Two-stage retrieval: dense recall (Chroma) -> Voyage rerank to a tight top-N.

The reranker is the main quality lever: it reorders broad dense candidates by
true query relevance, which matters for proper-noun-heavy anime queries.

Usage (Phase 1 gate check):
    python -m app.rag.retrieve "political thriller with moral ambiguity"
"""
import sys

from app import config
from app.services import chroma_collection, voyage_embed, voyage_rerank


class Candidate(dict):
    """A retrieved chunk: keys text, metadata, rerank_score."""


def retrieve(query: str, k: int | None = None, n: int | None = None) -> list[Candidate]:
    """Dense recall over chunks (cheap, local) -> collapse to distinct shows ->
    rerank the shows (Voyage, TPM-bounded).

    With multiple chunks per show (synopsis + reviews), the dense pool can hold
    several chunks of one show; we keep each show's best dense hit (the matching
    chunk — often a review for vibe queries) and rerank only `n` distinct shows so
    the reranker call stays under the free-tier 10K-tokens/minute cap.
    """
    k = k or config.RETRIEVE_K
    n = n or config.RERANK_N

    q_vec = voyage_embed([query], input_type="query")[0]

    collection = chroma_collection()
    res = collection.query(
        query_embeddings=[q_vec],
        n_results=k,
        include=["documents", "metadatas"],
    )
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    if not docs:
        return []

    # Collapse to distinct shows, keeping the best dense hit per show (Chroma
    # returns nearest-first, so the first chunk seen for a url is its best).
    seen: set[str] = set()
    pool_docs: list[str] = []
    pool_metas: list[dict] = []
    for doc, meta in zip(docs, metas):
        url = meta.get("source_url")
        if url in seen:
            continue
        seen.add(url)
        pool_docs.append(doc)
        pool_metas.append(meta)
        if len(pool_docs) >= n:
            break

    reranked = voyage_rerank(query, pool_docs, top_k=len(pool_docs))
    out: list[Candidate] = []
    for r in reranked:
        out.append(
            Candidate(
                text=pool_docs[r.index],
                metadata=pool_metas[r.index],
                rerank_score=r.relevance_score,
            )
        )
    return out


def main() -> None:
    query = " ".join(sys.argv[1:]) or "political thriller with moral ambiguity"
    cands = retrieve(query)
    print(f"Query: {query!r}\nReranked top {len(cands)}:\n")
    for i, c in enumerate(cands, 1):
        m = c["metadata"]
        print(f"[{i}] {m['anime_title']}  (score={c['rerank_score']:.3f})")
        print(f"    url: {m['source_url']}  source_type: {m['source_type']}")


if __name__ == "__main__":
    main()
