# Claude Code Session Prompt — Anime RAG Recommender
> Paste this at the start of every Claude Code session. Fill in Session Goal and Current State before coding begins.

---

## 🧭 Session Mode
Choose ONE and delete the other:
- **PLAN MODE** — Write full plan before any code is written
- **DIRECT MODE** — Edit loop, track unresolved errors in `ERRORS.md`

> After a few sessions, compare unresolved error delta between modes to find what works best for you.

---

## 📌 Project Context
**Project:** Anime RAG Recommender  
**Stack:** Python, FastAPI, ChromaDB, Anthropic API (claude-sonnet-4-6), Next.js/React  
**Data Sources:** AniList API (metadata + summaries), Reddit r/anime threads (scraped), MyAnimeList reviews  
**Current State:** . "Fresh start" 
**Session Goal:** "GET /recommend returns cited recs for a natural language query"

---

## ✅ Success Criteria
> Write this BEFORE any code or architecture decision this session.  
> A feature is only done when its condition is provably met — run it and check.

| Feature / Decision | Success When... |
|--------------------|-----------------|
| AniList data ingestion | 100+ shows fetched with title, synopsis, genres, score, and episode count stored as JSON |
| Reddit scrape | ≥50 r/anime threads chunked and stored in ChromaDB with source URL metadata |
| Embedding pipeline | ChromaDB returns top-5 semantically relevant chunks for the query "political thriller slow burn" |
| User preference store | After 3 queries, `/prefs` endpoint returns a taste profile with ≥2 inferred attributes |
| `/recommend` endpoint | POST with natural language query returns JSON: `recs[]` each with `title`, `score`, `reasoning`, `sources[]` |
| Citation requirement | Every rec's `sources[]` is non-empty — no answer generated without retrieval grounding it |
| Frontend query box | User types query → hits Enter → recs render with cited sources, no page reload |
| Preference persistence | Second session in the app still reflects prefs from first session |
| Deployed | `/recommend` reachable from public URL with a test query returning valid JSON |

> ⚠️ Before any redirect (swap vector DB, change data source, restructure API) — STOP. Add a row above with its success condition. Do not proceed without it.

---

## 🗺️ PLAN (Fill out fully before Claude Code writes any code)

### Phase 1 — Data Ingestion & Vector Store
- [ ] Fetch 100+ anime from AniList GraphQL API (title, synopsis, genres, score, episodes, MAL ID)
- [ ] Scrape or pull top r/anime threads via Pushshift or Reddit API, filter for rec/review threads
- [ ] Chunk all content (synopsis = 1 chunk, each review/thread = 1-3 chunks depending on length)
- [ ] Embed all chunks using Anthropic embeddings or sentence-transformers and store in ChromaDB
- [ ] Tag every chunk with metadata: `source_type` (anilist | reddit | mal), `source_url`, `anime_title`

**Phase 1 is done when:** ChromaDB query for "political thriller with moral ambiguity" returns ≥5 chunks with correct metadata attached.

---

### Phase 2 — Recommendation API
- [ ] Build FastAPI app with `/recommend` POST endpoint (accepts `query: str`, `user_id: str`)
- [ ] On query: embed it → retrieve top-k chunks from ChromaDB → pass to Claude with prompt
- [ ] Prompt instructs Claude to return structured JSON only: `recs[]` with `title`, `reasoning`, `sources[]`
- [ ] Build `/prefs` GET endpoint — reads user query history and infers taste profile via Claude
- [ ] Store user query history in SQLite keyed by `user_id`
- [ ] Validate: every rec must have at least 1 source — if retrieval returns nothing, say so instead of hallucinating

**Phase 2 is done when:** `POST /recommend` with `{"query": "I liked AOT for politics and pacing, what's similar?", "user_id": "test"}` returns ≥3 recs each with a non-empty `sources[]` array.

---

### Phase 3 — Frontend
- [ ] Next.js app with a single search page — text input + submit
- [ ] Render rec cards: show title, reasoning paragraph, cited sources as clickable links
- [ ] Show inferred taste profile badge (e.g. "You gravitate toward: political, slow burn, morally grey")
- [ ] Persist `user_id` in localStorage so prefs carry across sessions

**Phase 3 is done when:** A user can type "What should I watch after Vinland Saga if I'm burnt out on violence?" and see ≥2 rec cards with reasoning and at least 1 cited source link each.

---

### Phase 4 — Deploy
- [ ] Dockerize FastAPI backend
- [ ] Deploy backend to Render (or Railway)
- [ ] Deploy Next.js frontend to Vercel
- [ ] Smoke test: full query flow works end-to-end from public URL

**Phase 4 is done when:** The Vercel URL returns a working rec for a live query with no local server running.

---

## 🐛 Error Tracking (ERRORS.md convention)
> Log every error. If it's not resolved with a passing test or commit in this session, it's unresolved.

```
[YYYY-MM-DD] [ERROR] Description
[YYYY-MM-DD] [RESOLVED] What fixed it — commit hash or test name
[YYYY-MM-DD] [UNRESOLVED] Still open — carries to next session
```

**Session starts with N unresolved errors:** [ ]  
**Session ends with N unresolved errors:** [ ]  
**Delta:** [ ] ← Negative = good session.

---

## 🚦 Architecture Decision Log
> Every time you consider changing direction mid-session, log it here first. No redirect without a written success condition.

| Decision | Alternatives Considered | Success Criteria Written? | Outcome |
|----------|------------------------|--------------------------|---------|
| ChromaDB for vector store | Pinecone (paid/hosted), FAISS (no persistence) | ✅ | TBD |
| SQLite for user prefs | Redis (overkill), flat JSON (no concurrency) | ✅ | TBD |
| AniList as primary data source | MAL API (less flexible), static dataset (stale) | ✅ | TBD |

---

## 📋 Full Project Checklist
- [ ] AniList fetch script returns 100+ shows with full metadata
- [ ] Reddit threads chunked and embedded with source URL preserved
- [ ] ChromaDB seeded and returning semantically correct top-k results
- [ ] `/recommend` returns cited JSON recs — zero hallucinated sources
- [ ] `/prefs` returns inferred taste profile after ≥3 queries
- [ ] User query history persisted in SQLite
- [ ] Frontend renders rec cards with reasoning + clickable source citations
- [ ] Taste profile badge visible on frontend
- [ ] Tested with at least 5 natural language queries (see below)
- [ ] Deployed — public URL works end-to-end

### Test Queries (run all before marking done)
1. "I liked AOT for politics and pacing, what's similar?"
2. "What should I watch after Vinland Saga if I'm burnt out on violence?"
3. "Something emotionally devastating like Your Lie in April but less romance"
4. "Slow burn political thriller, I don't care about action"
5. "I want something fun and easy after watching Berserk"
