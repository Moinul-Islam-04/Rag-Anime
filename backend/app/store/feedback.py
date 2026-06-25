"""Saves (bookmarks) and votes (thumbs), keyed by user_id.

SQLAlchemy Core over the shared engine (SQLite locally, Postgres in prod).
Upserts are done as delete-then-insert to stay dialect-agnostic.
Votes feed recommendation generation (prefer liked, exclude disliked).
"""
import json
from datetime import datetime, timezone

from sqlalchemy import and_, delete, insert, select

from app.db import engine, saves, votes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- saves ---------------------------------------------------------------

def save_item(user_id: str, anime_url: str, rec_json: str) -> None:
    with engine.begin() as c:
        c.execute(
            delete(saves).where(
                and_(saves.c.user_id == user_id, saves.c.anime_url == anime_url)
            )
        )
        c.execute(
            insert(saves).values(
                user_id=user_id, anime_url=anime_url, rec_json=rec_json, created_at=_now()
            )
        )


def unsave_item(user_id: str, anime_url: str) -> None:
    with engine.begin() as c:
        c.execute(
            delete(saves).where(
                and_(saves.c.user_id == user_id, saves.c.anime_url == anime_url)
            )
        )


def list_saves(user_id: str) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(
            select(saves.c.rec_json)
            .where(saves.c.user_id == user_id)
            .order_by(saves.c.created_at.desc())
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


# --- votes ---------------------------------------------------------------

def set_vote(user_id: str, anime_url: str, vote: int, title: str, genres: list[str]) -> None:
    with engine.begin() as c:
        c.execute(
            delete(votes).where(
                and_(votes.c.user_id == user_id, votes.c.anime_url == anime_url)
            )
        )
        if vote != 0:  # 0 clears the vote
            c.execute(
                insert(votes).values(
                    user_id=user_id,
                    anime_url=anime_url,
                    vote=vote,
                    title=title,
                    genres=json.dumps(genres or []),
                    updated_at=_now(),
                )
            )


def get_votes(user_id: str) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(
            select(votes.c.anime_url, votes.c.vote, votes.c.title).where(
                votes.c.user_id == user_id
            )
        ).fetchall()
    return [{"anime_url": r[0], "vote": r[1], "title": r[2]} for r in rows]


def vote_context(user_id: str) -> tuple[list[str], list[str], set[str]]:
    """Return (liked_titles, disliked_titles, disliked_urls) for prompt + filtering."""
    votes_ = get_votes(user_id)
    liked = [v["title"] for v in votes_ if v["vote"] == 1 and v["title"]]
    disliked_titles = [v["title"] for v in votes_ if v["vote"] == -1 and v["title"]]
    disliked_urls = {v["anime_url"] for v in votes_ if v["vote"] == -1}
    return liked, disliked_titles, disliked_urls
