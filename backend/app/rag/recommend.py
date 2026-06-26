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
from app.meta import get_meta
from app.models import Rec, RecommendResponse, Source, Stream
from app.rag.retrieve import retrieve
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

    # No-sequel filtering: don't hand back a show the user named (or its other
    # seasons), and collapse multiple entries of the same franchise to one rec
    # (so "like AOT" can't surface AOT S1 *and* AOT Final Season).
    banned_franchises = referenced_franchises(query)
    seen_franchises: set[str] = set()
    deduped: list[dict] = []
    for c in candidates:  # already ordered best-first by the reranker
        fr = franchise_of(c["metadata"]["source_url"])
        if fr is not None:
            if fr in banned_franchises or fr in seen_franchises:
                continue
            seen_franchises.add(fr)
        deduped.append(c)
    candidates = deduped
    if not candidates:
        return RecommendResponse(
            query=query,
            recs=[],
            grounded=False,
            message="The only matches were the shows you named (or their sequels). Try a broader query.",
        )

    # Map of allowed citation URLs -> canonical title, from the retrieved set.
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
