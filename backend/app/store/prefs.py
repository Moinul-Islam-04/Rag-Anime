"""Per-user query history (SQLAlchemy Core; SQLite locally, Postgres in prod)."""
from datetime import datetime, timezone

from sqlalchemy import insert, select

from app.db import engine, query_history


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_query(user_id: str, query: str) -> None:
    with engine.begin() as c:
        c.execute(
            insert(query_history).values(user_id=user_id, query=query, created_at=_now())
        )


def get_history(user_id: str, limit: int = 50) -> list[str]:
    """Most-recent-first list of a user's past queries."""
    with engine.connect() as c:
        rows = c.execute(
            select(query_history.c.query)
            .where(query_history.c.user_id == user_id)
            .order_by(query_history.c.id.desc())
            .limit(limit)
        ).fetchall()
    return [r[0] for r in rows]
