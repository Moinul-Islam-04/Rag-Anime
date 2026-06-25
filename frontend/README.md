# Anime RAG Recommender — frontend

Next.js (App Router) single-page UI for the recommender. Type a taste query →
see cited recommendation cards → a taste-profile badge builds up as you search.

## Run

The backend must be running first (see `../backend/README.md`), then:

```bash
cd frontend
cp .env.local.example .env.local     # points at http://127.0.0.1:8000
npm install
npm run dev
```

Open <http://localhost:3000>.

## What it does

- **Search** → `POST /recommend`; rich rec cards: cover art, ⭐ score, genre
  pills, episodes·year, brand-colored streaming links, and clickable AniList
  **source links** (every card is cited — enforced by the backend). Cards fade in
  staggered with a hover lift; a skeleton/loading state shows while the pipeline
  runs.
- **Taste banner** → inferred attribute tags shown above the search bar.
- **Persistence** → a per-browser `user_id` in `localStorage`
  (`anime_rag_user_id`), so your taste profile carries across sessions.

### AniList login (optional but recommended)

Linking AniList seeds your taste profile from your **actual completed list**
(more accurate than inferring from queries) and flags shows you've **already
watched**.

1. Go to <https://anilist.co/settings/developer> → **Create New Client**.
2. Name it anything; set **Redirect URL** to `http://localhost:3000`.
3. Copy the **Client ID** into `frontend/.env.local`:
   `NEXT_PUBLIC_ANILIST_CLIENT_ID=12345`
4. Restart `npm run dev`. A **Link AniList** button appears top-right.

After linking:
- The taste banner switches to **"From your AniList history"**.
- Recs you've completed get a **✓ Watched** badge, with a **Hide already-watched**
  toggle.

The OAuth flow is implicit-grant and runs entirely in the browser — your AniList
token is stored in `localStorage` and **never sent to our backend** (only a
sample of watched titles+genres is, for taste inference).

## Config

`NEXT_PUBLIC_API_BASE` (in `.env.local`) — backend base URL. Set this to the
deployed backend URL when deploying to Vercel.

## Stack

Next.js 14 (App Router, JS) · React 18 · plain CSS (`app/globals.css`). No
component library — one page, `app/page.js`.
