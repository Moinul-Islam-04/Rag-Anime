"""Pydantic request/response models for the API."""
from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language taste query")
    user_id: str = Field("anon", description="Caller id (used later for prefs)")


class Stream(BaseModel):
    site: str
    url: str
    color: str | None = None


class Source(BaseModel):
    anime_title: str
    url: str
    cover_image: str | None = None
    score: int | None = None  # AniList averageScore, 0-100
    genres: list[str] = []
    episodes: int | None = None
    year: int | None = None
    streaming: list[Stream] = []
    chunk_text: str | None = None  # the retrieved chunk this rec is grounded in
    rerank_score: float | None = None  # Voyage rerank relevance (0-1)


class Rec(BaseModel):
    title: str
    reasoning: str
    sources: list[Source]


class RecommendResponse(BaseModel):
    query: str
    recs: list[Rec]
    grounded: bool = True  # False when retrieval produced no usable, cited recs
    message: str | None = None


class TasteProfile(BaseModel):
    user_id: str
    query_count: int  # number of signals used (queries, or watched shows)
    attributes: list[str]  # inferred taste tags, e.g. ["political", "slow burn"]
    summary: str | None = None
    source: str = "queries"  # "queries" | "anilist"
    message: str | None = None  # set when there isn't enough signal yet


class WatchedItem(BaseModel):
    title: str
    genres: list[str] = []


class SeedRequest(BaseModel):
    user_id: str = "anon"
    watched: list[WatchedItem] = []


class SaveRequest(BaseModel):
    user_id: str = "anon"
    rec: Rec


class UnsaveRequest(BaseModel):
    user_id: str = "anon"
    anime_url: str


class VoteRequest(BaseModel):
    user_id: str = "anon"
    anime_url: str
    vote: int  # 1 = up, -1 = down, 0 = clear
    title: str = ""
    genres: list[str] = []


class SavesResponse(BaseModel):
    saves: list[Rec]


class VotesResponse(BaseModel):
    votes: dict[str, int]  # anime_url -> vote
