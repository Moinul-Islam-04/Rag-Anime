# Architecture — Anime RAG Recommender

A deep-dive into how this app is built and **why** each technical decision was
made. Written to be read top-to-bottom: concepts first, then the request
lifecycle, then a decision-by-decision rationale.

## Contents
1. [What it does](#1-what-it-does)
2. [The big picture](#2-the-big-picture)
3. [The RAG pipeline](#3-the-rag-pipeline)
4. [A request, end to end](#4-a-request-end-to-end)
5. [Design decisions & rationale](#5-design-decisions--rationale)
6. [Data model](#6-data-model)
7. [Personalization & feedback loop](#7-personalization--feedback-loop)
8. [Deployment & ops](#8-deployment--ops)
9. [Security](#9-security)
10. [Cost & latency](#10-cost--latency)
11. [Limitations & future work](#11-limitations--future-work)
12. [File map](#12-file-map)

---

## 1. What it does

You describe your taste in plain English ("slow-burn political thriller, I don't
care about action") and get back anime recommendations where **every pick is
grounded in a real retrieved source** — no hallucinated titles. Optionally link
AniList to seed your taste from your actual watch history and hide shows you've
already seen.

The core engineering claim is **groundedness**: the system never returns a
recommendation it can't cite, and that's enforced in code, not just asked of the
model.

---

## 2. The big picture

```
┌─────────────────────┐      HTTPS       ┌──────────────────────────────────────┐
│  Frontend (Next.js)  │ ───────────────> │  Backend (FastAPI)                    │
│  - search UI         │ <─────────────── │  - /recommend, /prefs, /saves, ...    │
│  - AniList OAuth      │   cited JSON     │  - rate limiter (cost guard)          │
│  (Vercel)            │                  │  - RAG pipeline                       │
└─────────┬───────────┘                  └───┬─────────────┬──────────────┬──────┘
          │ browser-only                     │             │              │
          │ AniList token                    ▼             ▼              ▼
          ▼                          ┌────────────┐  ┌──────────┐  ┌────────────┐
   ┌──────────────┐                  │  ChromaDB   │  │  Voyage   │  │  Anthropic  │
   │ AniList API   │                  │ (vectors,   │  │ embed +   │  │ Claude      │
   │ (watch list)  │                  │  baked in)  │  │ rerank    │  │ (generate)  │
   └──────────────┘                  └────────────┘  └──────────┘  └────────────┘
                                            ▲
                                     ┌──────┴───────┐
                                     │ Postgres/Neon │  saves · votes · history
                                     │ (or SQLite)   │
                                     └──────────────┘
```

**Two processes, clean separation:**
- **Frontend** (Next.js on Vercel) — all UI, plus the AniList OAuth flow which
  runs *entirely in the browser* so the AniList token never touches our server.
- **Backend** (FastAPI on Render, in Docker) — the RAG pipeline and all
  persistence. Stateless except for the database and the (read-only) vector
  index baked into its image.

External services: **Voyage** (embeddings + reranking), **Anthropic Claude**
(generation), **AniList** (the anime corpus + optional user watch history).

---

## 3. The RAG pipeline

RAG = **Retrieval-Augmented Generation**. Instead of asking an LLM to recommend
anime from its training memory (which invites hallucinated titles, stale data,
and no sourcing), we:

1. **Retrieve** relevant anime from a vector database we control, then
2. **Generate** the recommendation *only from those retrieved candidates*, with
   the model forced to cite them.

This gives three properties a fine-tuned or memory-based model can't easily match:
- **Groundedness** — answers trace to a specific source.
- **Freshness** — update the corpus by re-running ingestion; no retraining.
- **Control** — we decide exactly what the model is allowed to recommend from.

### The two-stage retrieval (the heart of it)

```
query ──► Voyage embed ──► ChromaDB dense search (top 30) ──► Voyage rerank (top 10) ──► Claude
          (semantic vector)   (fast, approximate)              (precise relevance)
```

**Why two stages?** Dense vector search is fast but *approximate* — it's great at
"vibe" similarity but can rank a loosely-related show above a perfect match, and
it under-weights exact proper nouns (anime titles like "Vinland Saga"). A
**reranker** is a heavier cross-encoder model that looks at the query and each
candidate *together* and scores true relevance. So we cast a wide net cheaply
(top 30 by vector similarity), then a reranker precisely orders the best 10. The
reranker is the single biggest quality lever in the whole system.

### Ingestion (offline, run once)

```
AniList GraphQL ──► normalize ──► one chunk per show ──► Voyage embed ──► ChromaDB
(150 shows)         (clean HTML)   (title+genres+tags+    (document vectors)
                                    synopsis) + metadata
```

Each show becomes one "chunk" whose text leads with the title and tags (so proper
nouns are in the embedded text) and whose metadata carries everything needed to
cite it (`anime_title`, `source_url`, score, episodes, etc.). This runs locally;
the resulting index is committed and shipped with the backend.

---

## 4. A request, end to end

What actually happens on `POST /recommend {query, user_id}`:

1. **Rate-limit check** (`ratelimit.py`) — per-IP sliding window; 429 if over cap.
2. **Log the query** to the DB (`store/prefs.py`) for taste inference.
3. **Embed the query** (`services.voyage_embed`, `input_type="query"`) — served
   from an in-memory LRU cache if this exact query was embedded before.
4. **Dense search** ChromaDB over the chunk pool (synopsis + review chunks),
   then **collapse to distinct shows** keeping each show's best hit, and **rerank**
   those shows with Voyage `rerank-2.5` (`rag/retrieve.py`). Collapsing before the
   rerank keeps the call under the free-tier 10K-tokens/min cap.
5. **Apply feedback** — drop any shows the user thumbs-downed (`store/feedback.vote_context`).
6. **Community injection** (`recommend_graph.py`) — if the user *named* a show,
   seed the pool with its top AniList community "if you liked X" recs (in-corpus,
   vote-weighted, canonicalized to franchise flagships).
7. **No-sequel filtering** (`franchise.py`) — drop candidates from any franchise
   the user *named* (so "like AOT" never returns an AOT season), collapse multiple
   entries of one franchise to a single rec, and trim to `PROMPT_SHOWS` shows.
8. **Build the prompt** — for each show, merge its synopsis + top review summaries
   so Claude sees plot *and* viewer sentiment; number them with titles + URLs, plus
   a preference note ("user liked X, disliked Y") (`rag/recommend.py`).
9. **Call Claude** with **structured output** (a JSON schema) so the response is
   guaranteed-valid `{recs: [{title, reasoning, sources[]}]}`.
10. **Validate citations in code** — drop any rec whose `sources[]` URLs aren't in
    the retrieved candidate set. *This is the anti-hallucination guarantee.*
11. **Enrich** each surviving source with display metadata (cover, score, genres,
    streaming, plus the retrieved `chunk_text` + `rerank_score` for "Why this rec?").
12. **Return** the cited JSON. The frontend renders cards; nothing without a
    non-empty `sources[]` ever reaches the user.

---

## 5. Design decisions & rationale

### 5.1 Embeddings: Voyage (not "Anthropic embeddings", not local)
The original spec said "Anthropic embeddings" — but **Anthropic has no embeddings
API**. Claude is the *generation* model; embeddings need a different provider.
Options were local (`sentence-transformers`) or hosted (Voyage, OpenAI).
- **Chose Voyage `voyage-3.5`** for retrieval quality, and `rerank-2.5` for the
  reranker — Voyage is purpose-built for retrieval and is Anthropic's recommended
  embeddings partner.
- Tradeoff: a network dependency + a free-tier rate limit (see §10), vs. local
  embeddings which are free and offline but lower quality. For a recommender
  where retrieval quality *is* the product, hosted won.

### 5.2 Reranking is non-negotiable
Covered in §3. The lesson (from hybrid-search RAG practice): **retrieve broad,
rerank tight.** Anime queries are proper-noun-heavy, exactly where pure dense
retrieval is weakest and a reranker helps most. Verified empirically — "political
thriller with moral ambiguity" surfaces Psycho-Pass, Code Geass, Monster, FMA:B.

### 5.2b No-sequel filtering: a metadata join, not a vector-store rebuild
A good recommender shouldn't answer "something like Attack on Titan" with *Attack
on Titan: Final Season* — that's the show you already named. The fix needs to know
which titles belong to the same **franchise**. AniList exposes this via `relations`
(SEQUEL/PREQUEL/SIDE_STORY/PARENT/…), so ingestion now stores those edges per show.

Key decision: **franchises are computed at request time from `anime.json`, not
baked into the vector store.** A union-find over the relation edges groups shows
into franchises (connected components), and `recommend()` does two cheap set
operations on the reranked candidates — drop franchises named in the query, then
keep one entry per remaining franchise. Doing it as a metadata join means growing
or correcting the franchise map **never requires re-embedding** (the chunk text is
unchanged); the alternative — storing a `franchise_id` in Chroma metadata — would
force a re-embed on every adjustment. Query-naming is detected with title
*aliases* (the part before a subtitle `:`/`-`, season/part markers stripped) so a
user typing "Demon Slayer" matches the corpus's "Demon Slayer: Kimetsu no Yaiba".

### 5.2c Two extra signals from the same AniList API (no scraping)
Synopsis embeddings are **plot-descriptive**, but users query in **experiential /
comparative** language ("made me cry", "like AOT but for the politics") that
synopses don't contain. Two enrichments — both from the AniList API we already
call, fetched in a separate per-show pass (`ingest/anilist_enrich.py`) because
AniList's query-complexity cap forbids nesting them in the 50-per-page list query:

- **Community recommendation graph (`recommend_graph.py`).** AniList's
  `recommendations` are vote-weighted "if you liked X, watch Y" edges. When a query
  *names* a show, we inject its top in-corpus recs as candidates. Each rec is
  canonicalized to its **franchise flagship** (so "AOT Season 3 Part 2" → "Attack
  on Titan" and "Code Geass" + "R2" → one entry), and same-franchise recs are
  dropped by the no-sequel filter. This answers the highest-intent queries with
  *human-curated* matches instead of pure vector similarity — at zero embedding cost
  (it's a request-time `anime.json` join, like franchises).
- **Review-augmented retrieval.** Top review **summaries** (not bodies — bodies are
  spoiler-laden) become extra embedded chunks per show, so vibe queries finally have
  matching vocabulary to retrieve against. Verified: "made me ugly cry" now surfaces
  Clannad After Story, Your Lie in April, Plastic Memories — which synopsis-only
  retrieval missed.

Two consequences shaped the retrieval code. (1) Multiple chunks per show would let
one popular show flood the results, so `retrieve()` **collapses the dense pool to
distinct shows before the rerank** — which also bounds the rerank's token count
under the free tier's 10K/min cap. (2) The chunk that *retrieved* a show might be a
review, so the prompt builder **re-merges each kept show's synopsis + reviews from
`anime.json`**, guaranteeing Claude always sees plot and sentiment and never two
entries for one show. Review chunks reuse the show's `source_url`, so citation
validation and franchise collapse keep working unchanged.

### 5.3 Vector DB: ChromaDB (not Qdrant)
A real fork. Qdrant offers **native hybrid search** (dense + BM25 sparse), which
helps proper nouns. We chose **ChromaDB** because:
1. It's simpler (embedded, no separate service) and was the spec'd choice.
2. The Voyage **reranker recovers most of the hybrid benefit** on its own.
3. Fewer moving parts to ship.

We wrote down a **redirect trigger** in advance: *if title-anchored queries
("similar to Vinland Saga") miss in testing, switch to Qdrant hybrid.* They
didn't miss, so Chroma stands. The discipline of writing the upgrade condition
before needing it is the point.

> We pass our **own** Voyage vectors into Chroma (cosine space) rather than using
> Chroma's default embedder — so the index and query embeddings come from the same
> model, which is required for the distances to mean anything.

### 5.4 Generation: Claude with **structured outputs** + code-level citation checks
Two layers enforce groundedness:
1. **Structured output** (`output_config.format` with a JSON schema) guarantees
   the response *parses* into `{recs: [{title, reasoning, sources[]}]}`. We use
   this instead of "assistant prefill" because prefills return a 400 on Sonnet
   4.6.
2. **Code validation** — we don't *trust* the model to only cite real sources. We
   build the set of retrieved candidate URLs and **drop any rec whose sources
   aren't in it**. If nothing survives, we return an honest "no grounded match"
   instead of inventing.

The model is also instructed to recommend *only* from the numbered candidates.
But the instruction is the soft guard; the code filter is the hard guarantee.
Model: `claude-sonnet-4-6` — strong enough for grounded reasoning, and
cost-effective for an endpoint that runs on every search.

### 5.5 Rate limiter: in-memory sliding window (not slowapi, not Redis)
**Why a rate limiter at all?** Every `/recommend` call costs real money (2 Voyage
calls + 1 Claude call). A public RAG app with no cap is a billing incident waiting
for one person with a `for` loop. This is a **cost guard**, first and foremost.

**Why hand-rolled in-memory** (`ratelimit.py`) instead of a library?
- It's ~30 lines: a `deque` of timestamps per client IP, with a per-minute burst
  cap (12) and a per-day cap (150). A sliding window is the right model — it
  bounds both bursts and sustained abuse.
- **No new dependency.** `slowapi`/`limits` would add a package for something this
  small; Redis would add an entire piece of infrastructure.
- It's **correct for our deployment**: a single Render instance is one process, so
  one in-memory store sees all traffic.

**The explicit tradeoff** (documented in code): in-memory limits **reset on
restart** and are **per-instance**. If we ever scale to multiple instances, two
users could each get the full quota on different instances, and the limiter
should move to Redis (a shared store). For one free instance, in-memory is the
right amount of engineering — not under-built (we *do* have a guard), not
over-built (no Redis to operate). Knowing *when* the simple choice stops being
correct is the part worth articulating.

It's applied as a FastAPI **dependency** only on the two expensive LLM endpoints
(`/recommend`, `/prefs/seed`) — the cheap DB endpoints (saves/votes) aren't
limited, because they don't cost anything to abuse.

### 5.6 Persistence: SQLAlchemy Core, SQLite local → Postgres prod
User data (saves, votes, query history) needs to persist across deploys.
- **SQLAlchemy Core** (not the ORM) gives one code path that runs on **SQLite
  locally** (zero setup) and **Postgres in production** (Neon), switched by a
  single `DATABASE_URL` env var. Core over ORM because our access is simple
  table CRUD — we don't need entity mapping, relationships, or migrations
  machinery; Core's explicit `insert/select/delete` is lighter and clearer.
- **Upserts are done as delete-then-insert** rather than `ON CONFLICT`, because
  the upsert syntax differs between SQLite and Postgres. Delete-then-insert is
  portable across both dialects and fine at our write volume.
- Why not stay on SQLite in prod? Render's free filesystem is **ephemeral** — it
  resets on every deploy/restart, so SQLite there would silently lose saves and
  votes. Neon (managed Postgres, free tier) persists them.

### 5.7 Query-embedding cache (and why *not* a per-anime cache)
`voyage_embed` keeps an **LRU cache keyed by (input_type, text)**. Repeated
*queries* — example chips, retries, and especially **shared `/?q=` deep links** —
skip the Voyage call entirely (verified: ~1s → 0.0000s on a repeat).

Notably, we **don't** cache "recently recommended anime." That was considered and
rejected: the anime data (embeddings + metadata) is **already precomputed once at
ingestion** and stored locally, so there's no per-anime work at query time to
cache. The expensive steps (embed *query*, rerank, generate) are keyed on the
*query*, not on individual result shows — so caching at the query level is what
actually pays off. (Per-anime caching *would* matter if we later added an
expensive per-show op at request time, e.g. live streaming-availability lookups.)

### 5.8 AniList login: OAuth implicit grant, browser-only
Linking AniList pulls your real completed list to (a) seed taste from what you've
*watched* (stronger signal than what you've *searched*) and (b) badge/hide
already-seen shows.
- **Implicit grant** (not authorization-code) because there's no server-side
  secret to protect — the browser redirects to AniList, gets a token in the URL
  fragment, and calls the AniList GraphQL API directly.
- **The token never touches our backend.** Only a *sample* of watched
  titles+genres is sent, for taste inference. This keeps a user credential out of
  our logs and database entirely.
- Already-watched matching is pure frontend: parse the AniList id from each rec's
  source URL and check it against the completed-list ids.

### 5.9 Baked index in the Docker image
The Chroma index is only **2.9 MB**, so it's **committed to git and copied into
the Docker image** (read-only). The deployed backend needs **no ingestion or
embedding at startup** — it boots straight into serving. To refresh the corpus,
re-run ingestion locally and push; the new index ships with the next deploy.

---

## 6. Data model

Three tables (`app/db.py`), all keyed by the per-browser `user_id` (works
logged-in or not):

| Table | Columns | Purpose |
|---|---|---|
| `query_history` | id, user_id, query, created_at | feeds query-based taste profile |
| `saves` | (user_id, anime_url) PK, rec_json, created_at | bookmarks; stores the full rec for re-render |
| `votes` | (user_id, anime_url) PK, vote, title, genres, updated_at | 👍/👎; feeds recommendation personalization |

The **vector store** (ChromaDB) is separate and read-only: one collection
(`anime`) of document vectors + citation metadata. The **anime.json** file is a
flat metadata lookup (`meta.py`) joined to recommendations by URL to attach
covers/genres/streaming.

---

## 7. Personalization & feedback loop

Three signals, increasing in strength:
1. **Query history** → Claude infers a taste profile ("political · slow burn").
2. **Thumbs votes** → fed straight into generation: down-voted titles are
   **filtered out of candidates** (hard exclusion) and liked/disliked titles are
   passed to Claude as preference context ("lean toward similar"). This is the
   "recs improve over time" loop.
3. **AniList watch history** (when linked) → the strongest taste signal,
   inferred from what you've actually completed.

The taste profile is shown as a banner; when AniList is linked it switches to
"From your AniList history."

---

## 8. Deployment & ops

- **Backend** → Render (free Docker web service), via `render.yaml` blueprint.
- **Frontend** → Vercel (`NEXT_PUBLIC_API_BASE` points at the backend).
- **Database** → Neon (free Postgres) via `DATABASE_URL`.

**Free-tier cold starts:** Render free instances sleep after ~15 min idle (first
wake ~30–60s). Mitigated by (a) a **pre-warm** `fetch('/health')` on page load so
the server wakes when someone opens the app, and (b) an **uptime monitor**
(UptimeRobot / a GitHub Actions cron) pinging `/health` every ~10 min. CORS is
env-driven (`ALLOWED_ORIGINS`) plus a `*.vercel.app` allowance.

Full step-by-step in [`DEPLOY.md`](./DEPLOY.md).

---

## 9. Security

- **API keys** (Anthropic, Voyage) live only in backend env vars — never in the
  frontend bundle or git.
- **AniList tokens** stay in the browser (implicit grant); the backend never
  sees them.
- **CORS** restricts which origins may call the API.
- **Rate limiting** caps cost-incurring endpoints per IP.
- **Citation validation** prevents the model from surfacing anything not in the
  retrieved corpus — a content-integrity guard, not just a UX nicety.

---

## 10. Cost & latency

Per `/recommend`: **2 Voyage calls** (embed + rerank) + **1 Claude call**. Local
steps (Chroma search, metadata join, DB writes) are sub-millisecond.

**The dominant latency on free tier is the Voyage rate limit**, not compute. The
free Voyage tier (no payment method) is 3 requests/min, so we **throttle** calls
~21s apart (`VOYAGE_MIN_INTERVAL`) to avoid 429s — which makes a search take up to
~1 min. The UI sets that expectation with an elapsed timer + note. Adding a Voyage
payment method (the 200M free tokens still apply) lifts the limit; set
`VOYAGE_MIN_INTERVAL=0` and searches drop to a few seconds. The query-embedding
cache removes one of the two Voyage calls on repeated queries.

---

## 11. Limitations & future work

- **Corpus size** — 1,000 popular shows (synopsis + review chunks). Scaling further
  is just a larger ingestion run: bump `anilist --target`, re-run `anilist_enrich`,
  then `embed_index` only embeds new chunk ids (incremental + resumable per batch).
  At many thousands, revisit hybrid search / a hosted vector DB.
- **Data sources** — AniList only (synopsis + community recs + review summaries).
  Reddit ingestion (comparison megathreads) is the next source but needs entity
  resolution + OAuth; MAL/Jikan reviews are an easy fallback if AniList coverage
  thins for niche titles.
- **Rate limiter is per-instance** — move to Redis if scaling horizontally (§5.5).
- **No semantic dedup across a session** — could feed "recently recommended" into
  the next query for more diversity.
- **Reranker/effort tuning** — `RETRIEVE_K`/`RERANK_N` and the prompt are tuned by
  hand; an eval set would let us tune them quantitatively.

---

## 12. File map

```
backend/app/
  config.py          model ids, retrieval params (RETRIEVE_K/RERANK_N/PROMPT_SHOWS), paths
  services.py        Voyage/Anthropic/Chroma clients · throttle+retry · embedding cache
  db.py              SQLAlchemy engine + tables (SQLite local / Postgres prod)
  meta.py            anime.json metadata lookup by URL
  franchise.py       union-find over AniList relations → no-sequel filtering + flagship pick
  recommend_graph.py AniList community "if you liked X" graph (Phase A injection)
  models.py          pydantic request/response models
  ratelimit.py       in-memory per-IP sliding-window cost guard
  main.py            FastAPI app · endpoints · CORS
  ingest/
    anilist.py       AniList GraphQL fetch (+ franchise relations) → anime.json
    anilist_enrich.py  per-show pass adding community recs + review summaries
    chunk.py         show → synopsis chunk + review chunks + citation metadata
    embed_index.py   Voyage embed → ChromaDB upsert (incremental, resumable per batch)
  rag/
    retrieve.py      embed query → dense pool → collapse to shows → Voyage rerank
    recommend.py     community injection + no-sequel + synopsis/review merge + Claude + citation validation
    profile.py       taste inference (from queries or AniList watch history)
  store/
    prefs.py         query history
    feedback.py      saves + votes (+ vote_context for personalization)

frontend/app/
  page.js            the whole UI (search, cards, saves/votes/share, AniList login, states)
  anilist.js         OAuth implicit grant + GraphQL helpers (browser-only)
  globals.css        styling
  layout.js          root layout

deploy/
  backend/Dockerfile           bakes the read-only index, runs uvicorn
  render.yaml                  Render blueprint (env vars, health check)
  .github/workflows/keepalive.yml   pings /health to prevent cold starts
  DEPLOY.md                   step-by-step (Render + Vercel + Neon)
```
