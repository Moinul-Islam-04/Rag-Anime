"""FastAPI app: health + the cited recommendation endpoint.

Run:
    uvicorn app.main:app --reload
"""
import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    RecommendRequest,
    RecommendResponse,
    SaveRequest,
    SavesResponse,
    SeedRequest,
    TasteProfile,
    UnsaveRequest,
    VoteRequest,
    VotesResponse,
)
from app.db import init_db
from app.rag.profile import infer_from_watch_history, infer_taste_profile
from app.rag.recommend import recommend
from app.ratelimit import rate_limit
from app.store.feedback import (
    get_votes,
    list_saves,
    save_item,
    set_vote,
    unsave_item,
)
from app.store.prefs import get_history, log_query

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Anime RAG Recommender", version="0.2.0")

# CORS: defaults to the local Next.js dev server; set ALLOWED_ORIGINS
# (comma-separated) in production to your deployed frontend origin(s).
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",  # any Vercel preview/prod deploy
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()  # create all tables (query history, saves, votes)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/recommend", response_model=RecommendResponse, dependencies=[Depends(rate_limit)])
def recommend_endpoint(req: RecommendRequest) -> RecommendResponse:
    # Log the query for taste-profile inference; never let logging break a rec.
    try:
        log_query(req.user_id, req.query)
    except Exception as e:  # noqa: BLE001
        log.warning("query history logging failed: %s", e)
    try:
        return recommend(req.query, req.user_id)
    except RuntimeError as e:  # missing API keys, etc.
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 - surface upstream failures cleanly
        raise HTTPException(status_code=500, detail=f"recommend failed: {e}")


@app.get("/prefs", response_model=TasteProfile)
def prefs(user_id: str = "anon") -> TasteProfile:
    """Infer a taste profile from the user's query history (>=3 queries needed)."""
    try:
        history = get_history(user_id)
        return infer_taste_profile(user_id, history)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"prefs failed: {e}")


@app.post("/prefs/seed", response_model=TasteProfile, dependencies=[Depends(rate_limit)])
def prefs_seed(req: SeedRequest) -> TasteProfile:
    """Infer a taste profile from a sample of the user's AniList completed list."""
    try:
        return infer_from_watch_history(req.user_id, req.watched)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"seed failed: {e}")


# --- saves (bookmarks) ---------------------------------------------------

@app.get("/saves", response_model=SavesResponse)
def saves_list(user_id: str = "anon") -> SavesResponse:
    return SavesResponse(saves=list_saves(user_id))


@app.post("/saves", response_model=SavesResponse)
def saves_add(req: SaveRequest) -> SavesResponse:
    url = req.rec.sources[0].url if req.rec.sources else None
    if not url:
        raise HTTPException(status_code=400, detail="rec has no source url to key on")
    save_item(req.user_id, url, req.rec.model_dump_json())
    return SavesResponse(saves=list_saves(req.user_id))


@app.post("/saves/delete", response_model=SavesResponse)
def saves_delete(req: UnsaveRequest) -> SavesResponse:
    unsave_item(req.user_id, req.anime_url)
    return SavesResponse(saves=list_saves(req.user_id))


# --- votes (thumbs up/down) ----------------------------------------------

@app.get("/feedback", response_model=VotesResponse)
def feedback_get(user_id: str = "anon") -> VotesResponse:
    return VotesResponse(votes={v["anime_url"]: v["vote"] for v in get_votes(user_id)})


@app.post("/feedback", response_model=VotesResponse)
def feedback_set(req: VoteRequest) -> VotesResponse:
    set_vote(req.user_id, req.anime_url, req.vote, req.title, req.genres)
    return VotesResponse(votes={v["anime_url"]: v["vote"] for v in get_votes(req.user_id)})
