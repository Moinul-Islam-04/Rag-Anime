"""Generate cited recommendations from retrieved context with Claude.

Anti-hallucination guarantees (enforced in code, not just the prompt):
- Claude is given ONLY the reranked candidates and told to recommend solely
  from them.
- Structured JSON output (output_config.format) — no prefills (which 400 on
  Sonnet 4.6).
- Every returned rec is validated to have >=1 source whose URL belongs to the
  retrieved candidate set; sources/recs that fail are dropped.
"""
import json

from app import config
from app.franchise import franchise_of, referenced_franchises
from app.ingest.chunk import build_chunk
from app.meta import get_meta
from app.models import Rec, RecommendResponse, Source, Stream
from app.rag.retrieve import retrieve
from app.recommend_graph import injected_rec_urls
from app.services import anthropic_client
from app.store.feedback import vote_context

SYSTEM = (
    "You are an anime recommendation engine. You recommend shows ONLY from the "
    "candidate list provided in the user message. Never invent a title or a URL. "
    "For every recommendation, cite at least one candidate as a source using its "
    "exact title and URL. Aim for 3 to 5 recommendations when the candidates "
    "reasonably support the request, ordered best match first — but never pad the "
    "list with poor matches and never invent a title. If fewer than 3 candidates "
    "genuinely fit (or none do), return only those that do. Base your reasoning on "
    "the synopsis, genres, and tags shown."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "recs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "anime_title": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["anime_title", "url"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "reasoning", "sources"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recs"],
    "additionalProperties": False,
}


def _format_candidates(candidates: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(candidates, 1):
        m = c["metadata"]
        blocks.append(
            f"[{i}] Title: {m['anime_title']}\n"
            f"URL: {m['source_url']}\n"
            f"{c['text']}"
        )
    return "\n\n".join(blocks)


def _enrich_source(url: str, title: str, cand: dict | None) -> Source:
    """Attach display metadata (from anime.json) + retrieval provenance (from the candidate)."""
    m = get_meta(url) or {}
    return Source(
        anime_title=title,
        url=url,
        cover_image=m.get("cover_image") or None,
        score=m.get("score") or None,
        genres=m.get("genres", []),
        episodes=m.get("episodes") or None,
        year=m.get("year") or None,
        streaming=[Stream(**s) for s in m.get("streaming", [])],
        chunk_text=(cand or {}).get("text"),
        rerank_score=(cand or {}).get("rerank_score"),
    )


def _preference_note(liked: list[str], disliked: list[str]) -> str:
    note = ""
    if liked:
        note += (
            "\nThe user previously gave a thumbs-up to: "
            + ", ".join(liked[:15])
            + ". Lean toward picks consistent with those tastes."
        )
    if disliked:
        note += (
            "\nThe user gave a thumbs-down to: "
            + ", ".join(disliked[:15])
            + ". Avoid recommendations with a similar tone or appeal."
        )
    return note


def _candidate_from_url(url: str) -> dict | None:
    """Build a synthetic retrieval candidate for an injected community rec, using
    the show's anime.json record. Shaped like a `retrieve()` Candidate so it flows
    through the franchise collapse, citation map, and enrichment unchanged."""
    show = get_meta(url)
    if not show:
        return None  # recommended title isn't in our corpus
    chunk = build_chunk(show)
    return {"text": chunk["text"], "metadata": chunk["metadata"], "rerank_score": 1.0}


def _merged_candidate(url: str, rerank_score: float) -> dict | None:
    """One prompt candidate per show: synopsis + top review summaries, rebuilt from
    anime.json so Claude sees plot AND viewer sentiment whichever chunk retrieved."""
    show = get_meta(url)
    if not show:
        return None
    chunk = build_chunk(show)
    text = chunk["text"]
    reviews = (show.get("reviews") or [])[: config.REVIEW_CHUNKS_PER_SHOW]
    if reviews:
        text += "\n\nWhat viewers say:\n" + "\n".join(f"- {r['summary']}" for r in reviews)
    return {"text": text, "metadata": chunk["metadata"], "rerank_score": rerank_score}


def _call_claude(query: str, candidates: list[dict], pref_note: str = "") -> dict:
    user_msg = (
        f"User request: {query}\n{pref_note}\n\n"
        f"Candidates (recommend only from these):\n\n"
        f"{_format_candidates(candidates)}"
    )
    resp = anthropic_client().messages.create(
        model=config.GEN_MODEL,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def recommend(query: str, user_id: str = "anon") -> RecommendResponse:
    candidates = retrieve(query)
    if not candidates:
        return RecommendResponse(
            query=query,
            recs=[],
            grounded=False,
            message="No anime in the index matched your query.",
        )

    # Personalize from thumbs feedback: drop down-voted titles, nudge toward up-voted.
    liked, disliked_titles, disliked_urls = vote_context(user_id)
    candidates = [c for c in candidates if c["metadata"]["source_url"] not in disliked_urls]
    if not candidates:
        return RecommendResponse(
            query=query,
            recs=[],
            grounded=False,
            message="Every match was a title you down-voted. Try a different query.",
        )

    banned_franchises = referenced_franchises(query)

    # Phase A — community graph: when the user NAMES a show, seed the pool with
    # its top AniList community "if you liked X, watch Y" recs (in-corpus, vote-
    # weighted, same-franchise already excluded). Front-inserted with a max score
    # so they win the per-franchise collapse below; deduped against retrieval.
    have_urls = {c["metadata"]["source_url"] for c in candidates}
    injected: list[dict] = []
    for url in injected_rec_urls(query, banned_franchises, config.COMMUNITY_INJECT_MAX):
        if url in have_urls:
            continue
        cand = _candidate_from_url(url)
        if cand:
            injected.append(cand)
            have_urls.add(url)
    candidates = injected + candidates

    # Collapse chunks -> shows. A show can now contribute a synopsis chunk AND
    # several review chunks; group by url, keeping each show's best rerank score
    # and the reranker's first-seen ordering (injected community recs lead).
    show_score: dict[str, float] = {}
    order: list[str] = []
    for c in candidates:
        url = c["metadata"]["source_url"]
        score = c.get("rerank_score") or 0.0
        if url not in show_score:
            show_score[url] = score
            order.append(url)
        else:
            show_score[url] = max(show_score[url], score)

    # No-sequel filtering: drop a franchise the user named (or its other seasons),
    # keep one entry per franchise, and cap the distinct shows sent to Claude.
    seen_franchises: set[str] = set()
    kept_urls: list[str] = []
    for url in order:
        fr = franchise_of(url)
        if fr is not None:
            if fr in banned_franchises or fr in seen_franchises:
                continue
            seen_franchises.add(fr)
        kept_urls.append(url)
        if len(kept_urls) >= config.PROMPT_SHOWS:
            break
    if not kept_urls:
        return RecommendResponse(
            query=query,
            recs=[],
            grounded=False,
            message="The only matches were the shows you named (or their sequels). Try a broader query.",
        )

    # Merge each kept show into ONE candidate (synopsis + its top review summaries,
    # rebuilt from anime.json) so Claude always sees plot AND viewer sentiment
    # regardless of which chunk drove retrieval — and never two entries per show.
    candidates = [c for url in kept_urls if (c := _merged_candidate(url, show_score[url]))]

    # Map of allowed citation URLs -> canonical title, from the surviving set.
    allowed = {c["metadata"]["source_url"]: c["metadata"]["anime_title"] for c in candidates}
    cand_by_url = {c["metadata"]["source_url"]: c for c in candidates}

    raw = _call_claude(query, candidates, _preference_note(liked, disliked_titles))

    validated: list[Rec] = []
    for rec in raw.get("recs", []):
        good_sources = [
            _enrich_source(s["url"], allowed[s["url"]], cand_by_url.get(s["url"]))
            for s in rec.get("sources", [])
            if s.get("url") in allowed
        ]
        if not good_sources:
            continue  # citation guarantee: drop uncited / hallucinated recs
        validated.append(
            Rec(
                title=rec.get("title", "").strip(),
                reasoning=rec.get("reasoning", "").strip(),
                sources=good_sources,
            )
        )

    if not validated:
        return RecommendResponse(
            query=query,
            recs=[],
            grounded=False,
            message="Retrieval found candidates but none could be confidently recommended.",
        )

    return RecommendResponse(query=query, recs=validated, grounded=True)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "I liked AOT for politics and pacing, what's similar?"
    print(recommend(q).model_dump_json(indent=2))
