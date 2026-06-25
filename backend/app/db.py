"""Database engine + table definitions (SQLAlchemy Core).

One code path, two dialects:
- Local dev: no DATABASE_URL -> SQLite file at data/app.db (zero setup).
- Production: DATABASE_URL=postgresql://...  -> hosted Postgres (e.g. Neon).
"""
import os

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)

from app import config


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{config.DB_PATH}"
    # SQLAlchemy 2.0 needs the 'postgresql://' scheme (some hosts emit 'postgres://').
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


_url = _db_url()
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}
engine = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)

metadata = MetaData()

query_history = Table(
    "query_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String, nullable=False, index=True),
    Column("query", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

saves = Table(
    "saves",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("anime_url", String, primary_key=True),
    Column("rec_json", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

votes = Table(
    "votes",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("anime_url", String, primary_key=True),
    Column("vote", Integer, nullable=False),
    Column("title", Text),
    Column("genres", Text),
    Column("updated_at", String, nullable=False),
)


def init_db() -> None:
    """Create all tables if they don't exist (idempotent)."""
    metadata.create_all(engine)
