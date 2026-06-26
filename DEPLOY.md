# Deploy — Anime RAG Recommender

Backend → **Render** (free Docker web service). Frontend → **Vercel**. Database →
**Neon** (free Postgres). All free-tier.

Architecture in prod:
```
Vercel (Next.js)  ──HTTPS──>  Render (FastAPI + baked Chroma index)  ──>  Neon Postgres
                                     │                                         (saves/votes/history)
                                     └── Anthropic + Voyage APIs
```

The 2.9 MB Chroma index is committed to the repo and baked into the Docker
image, so the backend needs **no re-ingestion** on deploy.

---

## 0. Prerequisites (accounts)
- GitHub, [Render](https://render.com), [Neon](https://neon.tech), [Vercel](https://vercel.com) — all free.
- Your AniList client ID (you have one). See the AniList note in step 6 about prod redirect URLs.

## 1. Push to GitHub
From the project root (`Rag-Anime/`):
```bash
git init
git add .
git commit -m "Anime RAG recommender"
git branch -M main
git remote add origin https://github.com/<you>/anime-rag.git
git push -u origin main
```
The `.gitignore` commits the prebuilt index (`backend/data/anime.json`, `backend/data/chroma/`) but excludes secrets and the local SQLite file.

## 2. Create the Neon database
1. Neon → **New Project**.
2. Copy the **pooled** connection string (Dashboard → Connect → toggle **Pooled connection**). It looks like:
   `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`
3. Keep it for step 3. (Pooled = handles many short-lived connections, which suits a web app.)

## 3. Deploy the backend (Render)
1. Render → **New + → Blueprint** → connect your GitHub repo. It reads `render.yaml`.
2. When prompted, set the secret env vars:
   - `ANTHROPIC_API_KEY` — your Anthropic key
   - `VOYAGE_API_KEY` — your Voyage key
   - `DATABASE_URL` — the Neon pooled string from step 2
   - `ALLOWED_ORIGINS` — leave blank for now (set in step 5)
   - `VOYAGE_MIN_INTERVAL` — `21` (already in the blueprint; see notes)
3. Deploy. Note the backend URL, e.g. `https://anime-rag-backend.onrender.com`.
4. Smoke test: `curl https://anime-rag-backend.onrender.com/health` → `{"status":"ok"}`.
   Tables are auto-created in Neon on first boot.

## 4. Deploy the frontend (Vercel)
1. Vercel → **Add New → Project** → import the repo.
2. Set **Root Directory** to `frontend`.
3. Environment variables:
   - `NEXT_PUBLIC_API_BASE` = your Render backend URL (from step 3)
   - `NEXT_PUBLIC_ANILIST_CLIENT_ID` = your AniList client ID
4. Deploy. Note the frontend URL, e.g. `https://anime-rag.vercel.app`.

## 5. Point CORS at the frontend
On Render, set `ALLOWED_ORIGINS` = your Vercel URL (e.g. `https://anime-rag.vercel.app`) → Render redeploys automatically.
> Note: the backend already allows any `*.vercel.app` origin via regex, so the app works even before this — but pinning your exact domain is cleaner.

## 6. AniList redirect URL (for login in prod)
AniList allows **one redirect URL per client**. To keep both local and prod working, create a **second** AniList client at <https://anilist.co/settings/developer> with Redirect URL = your Vercel URL, and use that client's ID for `NEXT_PUBLIC_ANILIST_CLIENT_ID` in Vercel. (Keep the localhost client for local dev.)

## 7. Eliminate cold starts (keepalive)
Free Render instances sleep after ~15 min idle (first wake ~30–60s). Mitigations already built in:
- **Pre-warm:** the frontend pings `/health` on page load, so the server wakes when someone opens the app.
- **Health check:** `render.yaml` sets `healthCheckPath: /health`.

To keep it always warm, do **one** of:
- **UptimeRobot** (recommended) — free monitor hitting `https://<backend>.onrender.com/health` every 5 min.
- **GitHub Actions** — `.github/workflows/keepalive.yml` pings every ~12 min. Set your URL **without editing the file**: repo → Settings → Secrets and variables → Actions → **Variables** → New variable, name `BACKEND_URL`, value `https://<your>.onrender.com`. (Falls back to the `render.yaml` service name `anime-rag-backend` if unset.) The job retries through cold-start 502s, so it wakes a sleeping instance instead of failing.

## 8. Final smoke test
Open the Vercel URL → run a query → confirm cited cards render. Save one, refresh
→ it persists (Neon). Link AniList → watch-history taste + watched badges.

---

## Notes
- **~1 min searches** on free Voyage tier (3 RPM throttle). The loading UI sets this expectation. To make it fast: add a payment method on Voyage (your 200M free tokens still apply), then set `VOYAGE_MIN_INTERVAL=0` on Render.
- **Persistence:** saves/votes/history live in Neon and survive redeploys. (AniList login + taste live in the browser regardless.)
- **Rate limiting** is in-memory per instance (`12/min`, `150/day`). On a single free instance that's fine; if you scale to multiple instances, move it to Redis.
- **Index updates:** to refresh the anime library, re-run ingestion locally (`python -m app.ingest.anilist && python -m app.ingest.embed_index`), commit the updated `data/`, and push — Render redeploys with the new index.
