# Anime RAG Recommender — backend

RAG-based anime recommendations: AniList metadata → Voyage embeddings in ChromaDB
→ Voyage reranker → Claude (`claude-sonnet-4-6`) → cited JSON recommendations.

Every recommendation is grounded: `sources[]` is never empty — uncited or
hallucinated recs are dropped in code before the response is returned.

## Pipeline

```
query → Voyage embed → ChromaDB dense top-30 → Voyage rerank-2.5 top-6
      → Claude (structured JSON) → validate citations → RecommendResponse
```

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY
```

## Build the index (run once)

```bash
python -m app.ingest.anilist          # → data/anime.json (~120 shows)
python -m app.ingest.embed_index      # embed + load ChromaDB
```

## Quick checks

```bash
# Phase 1 gate: reranked retrieval with metadata
python -m app.rag.retrieve "political thriller with moral ambiguity"

# Phase 2 gate: full cited recommendation (needs ANTHROPIC_API_KEY)
python -m app.rag.recommend "I liked AOT for politics and pacing, what's similar?"
```

## Run the API

```bash
uvicorn app.main:app --reload
```

```bash
curl -s localhost:8000/health

# cited recommendations (also logs the query to the user's history)
curl -s -X POST localhost:8000/recommend \
  -H 'content-type: application/json' \
  -d '{"query":"I liked AOT for politics and pacing, what'\''s similar?","user_id":"test"}' | jq

# taste profile inferred from query history (needs >=3 queries for that user)
curl -s "localhost:8000/prefs?user_id=test" | jq
```

Interactive docs: open `http://127.0.0.1:8000/docs`.

## Endpoints
- `GET /health` — liveness.
- `POST /recommend` `{query, user_id}` — cited recs; every rec has a non-empty `sources[]` (each carries cover/score/genres/year/streaming + the retrieved `chunk_text` & `rerank_score`). Logs the query; personalizes from the user's votes (excludes down-voted, leans toward up-voted). Rate-limited per IP.
- `GET /prefs?user_id=` — taste profile from query history (≥3 queries).
- `POST /prefs/seed` `{user_id, watched:[{title,genres}]}` — taste profile from AniList watch history. Rate-limited.
- `GET /saves?user_id=` · `POST /saves {user_id, rec}` · `POST /saves/delete {user_id, anime_url}` — bookmarks.
- `GET /feedback?user_id=` · `POST /feedback {user_id, anime_url, vote, title, genres}` — thumbs up/down (vote ∈ 1/-1/0).

Rate limiting: in-memory per-IP, 12/min + 150/day on the LLM endpoints (`app/ratelimit.py`).

## Config

`app/config.py` — model ids (`voyage-3.5`, `rerank-2.5`, `claude-sonnet-4-6`),
retrieval params (`RETRIEVE_K=30`, `RERANK_N=10`), and paths.

Environment:
- `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` — required.
- `DATABASE_URL` — optional. Unset → SQLite at `data/app.db` (local dev). Set to
  a Postgres URL (e.g. Neon) in production for persistent saves/votes/history.
- `ALLOWED_ORIGINS` — comma-separated CORS origins (default localhost:3000).
- `VOYAGE_MIN_INTERVAL` — seconds between Voyage calls (default `21` for the free
  tier; set `0` on a paid Voyage plan).

Query embeddings are cached in-memory (LRU) so repeated queries (example chips,
retries, shared `/?q=` links) skip the Voyage call.

## Deploy

See [`../DEPLOY.md`](../DEPLOY.md) — Render (backend) + Vercel (frontend) + Neon
(Postgres), all free tier. The prebuilt Chroma index is committed and baked into
the Docker image, so deploys need no re-ingestion.

## Not yet built (next sessions)

- Reddit / MAL ingestion (Phase 1 expansion)
- Next.js frontend (Phase 3), deploy (Phase 4)
- Redirect on file if title-anchored retrieval is weak: Qdrant hybrid (dense+BM25)
  — see plan's "Redirect trigger".
