# ERRORS.md — Anime RAG Recommender

> Log every error. If it's not resolved with a passing test/commit this session, it's unresolved.

```
[YYYY-MM-DD] [ERROR] Description
[YYYY-MM-DD] [RESOLVED] What fixed it — commit hash or test name
[YYYY-MM-DD] [UNRESOLVED] Still open — carries to next session
```

## Session 2026-06-25 — AniList → /recommend with citations

**Session starts with N unresolved errors:** 0
**Session ends with N unresolved errors:** 0
**Delta:** 0

### Log
- [2026-06-25] [INFO] Spec said "Anthropic embeddings" — Anthropic has no embeddings API. Switched to Voyage AI (voyage-3.5 + rerank-2.5). Logged in Architecture Decision Log.
- [2026-06-25] [ERROR] Voyage `RateLimitError` on embed_index: free tier without payment method is 3 RPM / 10K TPM; a 100-text batch exceeded it.
- [2026-06-25] [RESOLVED] Added throttle (`VOYAGE_MIN_INTERVAL`, default 21s) + rate-limit retry in `app/services.py` (`voyage_embed`/`voyage_rerank`); reduced `EMBED_BATCH` to 16. All 150 chunks indexed cleanly. Unlock: add a payment method in Voyage dashboard (free 200M tokens still apply), then set `VOYAGE_MIN_INTERVAL=0`.
- [2026-06-25] [ERROR] Phase 2 gate: queries Q2 ("burnt out on violence") and Q3 ("less romance") returned only 2 recs (< 3 required). Not hallucination — model was conservative against a 6-candidate pool. Citations were 100% correct throughout.
- [2026-06-25] [RESOLVED] Widened pool `RERANK_N` 6→10 + prompt nudge to aim for 3–5 recs when candidates support it (no padding/inventing). Re-test: Q2→3 recs, Q3→5 recs, all cited. All 5 test queries PASS.
- [2026-06-25] [RESOLVED] Phase 1 gate PASS: "political thriller with moral ambiguity" → Psycho-Pass, Code Geass, FMA:B, Monster (6 chunks, all w/ metadata).
- [2026-06-25] [RESOLVED] Phase 2 gate PASS: live `POST /recommend` over HTTP returns ≥3 cited recs; citation guarantee (non-empty `sources[]`) holds on all 5 spec queries.

### Phase 2 finish — SQLite history + /prefs taste profile
- [2026-06-25] [RESOLVED] Added `app/store/prefs.py` (SQLite query history) + `app/rag/profile.py` (Claude taste inference). `/recommend` now logs each query; `GET /prefs?user_id=` infers a profile from ≥3 queries.
- [2026-06-25] [RESOLVED] Prefs gate PASS: 3 seeded queries → 6 attribute tags + summary (≥2 required); under-3 returns a "need more queries" message. HTTP wiring confirmed (recommend logs history; /prefs reads it).
- [2026-06-25] [INFO] During verification, background uvicorn hit "address already in use" — a previously-started dev server was still bound to :8000 and auto-reloaded the new code. Not a code error.

### Phase 3 — Next.js frontend
- [2026-06-25] [RESOLVED] Built `frontend/` (Next 14 App Router, JS): search box → cited rec cards → taste badge; user_id persisted in localStorage. Added CORS middleware to backend for localhost:3000.
- [2026-06-25] [ERROR] `next@14.2.15` flagged with a security vulnerability on install.
- [2026-06-25] [RESOLVED] Upgraded to `next@14.2.35` (patched). Dev server runs; page serves 200; CORS preflight from :3000 returns allow-origin. End-to-end pieces verified (backend /recommend + /prefs reachable cross-origin).

### Phase 3.1 — rich rec cards
- [2026-06-25] [RESOLVED] Enriched AniList ingestion with coverImage, seasonYear, and STREAMING externalLinks (incl. AniList brand colors); re-ran ingest (no re-embed). Added `app/meta.py` lookup + expanded `Source` model; `/recommend` now returns cover/score/genres/episodes/year/streaming per source. Verified live (The Apothecary Diaries: cover, ⭐88, 2023, 24 eps, Crunchyroll/Netflix/Hulu).
- [2026-06-25] [RESOLVED] Frontend rich cards: cover thumbnail, score badge, genre pills, eps·year, brand-colored streaming pills, hover lift/glow, staggered fade-in, taste banner above search, filled active chip. Compiles clean (HTTP 200).

### Phase 3.2 — pre-deploy polish (AniList login, watched filter, loading state)
- [2026-06-25] [RESOLVED] Backend: `POST /prefs/seed` infers a taste profile from a watch-history sample (titles+genres); `profile.infer_from_watch_history`; `TasteProfile.source` ∈ queries|anilist. Verified live (thriller watch list → psychological/thriller/dark/mystery).
- [2026-06-25] [RESOLVED] Frontend: AniList OAuth (implicit grant, browser-only; token never hits backend) via `app/anilist.js`; Link/Logout UI; watch-history-seeded taste banner; already-watched ✓ badge + hide toggle (matches recs' AniList id from source URL to completed list); loading skeleton cards + "searching sources" pulse.
- [2026-06-25] [RESOLVED] AniList login verified working by user (client 44333). Note: user pasted a live access token in chat → advised revoke via AniList Settings→Apps + remove the unused NEXT_PUBLIC_ANILIST_CLIENT_SECRET (exposed in browser bundle).

### Phase 3.3 — pre-deploy hardening + RAG flex (Wave 1)
- [2026-06-25] [RESOLVED] Cost guard: `app/ratelimit.py` in-memory per-IP sliding window (12/min, 150/day) as a dependency on /recommend + /prefs/seed. Verified: 12 allowed then 429.
- [2026-06-25] [RESOLVED] "Why this rec?": Source now carries chunk_text + rerank_score; frontend expandable shows the retrieved chunk + Voyage relevance. Verified live (chunk 989 chars, score 0.32).
- [2026-06-25] [RESOLVED] Polished empty state (suggestions) + error state (retry button; distinct 429 'easy there' message). Frontend compiles clean.

### Phase 3.4 — engagement (Wave 2): saves, thumbs feedback, share
- [2026-06-25] [RESOLVED] Backend: `store/feedback.py` (saves + votes tables, keyed by user_id); endpoints GET/POST /saves, POST /saves/delete, GET/POST /feedback. Verified save→list→unsave + vote persist.
- [2026-06-25] [RESOLVED] Thumbs feed recs: `recommend(query, user_id)` excludes down-voted titles from candidates and passes liked/disliked preference context to Claude. Verified: down-voted Monster excluded from w2's recs.
- [2026-06-25] [RESOLVED] Frontend: per-card heart (save), 👍/👎 (vote), ↗ Share (copies /?q= deep link); Saved view toggle; ?q= deep-link reproduces a search on load; copy toast. Compiles clean; deep-link route 200.

### Phase 4 — deploy prep
- [2026-06-25] [RESOLVED] Query-embedding LRU cache in services.voyage_embed (keyed by input_type+text). Verified: repeat query 1.0s→0.0000s.
- [2026-06-25] [RESOLVED] Deploy artifacts: Dockerfile (bakes 2.9MB index, no re-ingest), .dockerignore, env-driven ALLOWED_ORIGINS, chromadb pinned ==1.5.9, render.yaml blueprint, keepalive GH Action, DEPLOY.md (Render+Vercel+Neon walkthrough).
- [2026-06-25] [RESOLVED] Persistence: migrated stores to SQLAlchemy Core (app/db.py) — SQLite locally, Postgres (Neon) in prod via DATABASE_URL. Rewrote store/prefs + store/feedback; single init_db(). Verified save/list/vote/unsave on SQLite + clean imports.
- [2026-06-25] [RESOLVED] Free-tier UX: frontend pre-warm ping to /health on load; loading state shows elapsed timer + '~1 min on free tier' note.
