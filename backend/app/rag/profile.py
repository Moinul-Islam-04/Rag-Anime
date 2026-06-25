"""Infer a user's anime taste profile.

Two signals, same structured-output shape:
- query history (what they searched for)  -> infer_taste_profile
- AniList completed list (what they watched) -> infer_from_watch_history

Watch history is the stronger signal and is preferred by the frontend once the
user links AniList. The backend stays stateless: it infers from whatever sample
it's handed and persists nothing AniList-specific.
"""
import json

from app import config
from app.models import TasteProfile, WatchedItem
from app.services import anthropic_client

MIN_QUERIES = 3  # a query-based profile is inferred after >= 3 queries
MAX_WATCHED = 40  # cap the watch-history sample sent to the model

SCHEMA = {
    "type": "object",
    "properties": {
        "attributes": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["attributes", "summary"],
    "additionalProperties": False,
}

QUERY_SYSTEM = (
    "You infer an anime viewer's taste profile from their recent search queries. "
    "Return 2 to 6 short lowercase attribute tags capturing recurring themes, tone, "
    "or preferences (e.g. 'political', 'slow burn', 'morally grey', 'emotional', "
    "'low romance', 'action-light'), plus a one-sentence summary written to the user "
    "('You gravitate toward ...'). Base everything ONLY on the queries; do not invent "
    "specific titles or facts not implied by them."
)

HISTORY_SYSTEM = (
    "You infer an anime viewer's taste profile from their completed/watched list "
    "(titles, with genres in parentheses). Return 3 to 6 short lowercase attribute "
    "tags capturing recurring themes, tone, and genre leanings (e.g. 'action', "
    "'psychological', 'slice of life', 'shounen', 'emotional', 'dark fantasy'), plus "
    "a one-sentence summary written to the user ('You gravitate toward ...'). Base "
    "everything ONLY on the provided shows."
)


def _infer(system: str, user_content: str, user_id: str, count: int, source: str) -> TasteProfile:
    resp = anthropic_client().messages.create(
        model=config.GEN_MODEL,
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    attributes = [a.strip().lower() for a in data.get("attributes", []) if a.strip()][:6]
    return TasteProfile(
        user_id=user_id,
        query_count=count,
        attributes=attributes,
        summary=(data.get("summary") or "").strip() or None,
        source=source,
    )


def infer_taste_profile(user_id: str, queries: list[str]) -> TasteProfile:
    if len(queries) < MIN_QUERIES:
        return TasteProfile(
            user_id=user_id,
            query_count=len(queries),
            attributes=[],
            source="queries",
            message=(
                f"Need at least {MIN_QUERIES} queries to infer a taste profile; "
                f"have {len(queries)}."
            ),
        )
    content = "Recent queries:\n" + "\n".join(f"- {q}" for q in queries)
    return _infer(QUERY_SYSTEM, content, user_id, len(queries), "queries")


def infer_from_watch_history(user_id: str, watched: list[WatchedItem]) -> TasteProfile:
    watched = watched[:MAX_WATCHED]
    if not watched:
        return TasteProfile(
            user_id=user_id,
            query_count=0,
            attributes=[],
            source="anilist",
            message="No watch history provided.",
        )
    lines = []
    for w in watched:
        genres = f" ({', '.join(w.genres)})" if w.genres else ""
        lines.append(f"- {w.title}{genres}")
    content = "Completed/watched anime:\n" + "\n".join(lines)
    return _infer(HISTORY_SYSTEM, content, user_id, len(watched), "anilist")
