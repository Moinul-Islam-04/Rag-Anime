"use client";

import { useEffect, useState } from "react";
import {
  CLIENT_ID,
  loginUrl,
  readTokenFromHash,
  fetchViewer,
  fetchCompleted,
  anilistIdFromUrl,
} from "./anilist";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

const EXAMPLES = [
  "I liked AOT for politics and pacing, what's similar?",
  "What should I watch after Vinland Saga if I'm burnt out on violence?",
  "Something emotionally devastating like Your Lie in April but less romance",
  "Slow burn political thriller, I don't care about action",
];

function getUserId() {
  if (typeof window === "undefined") return "anon";
  let id = localStorage.getItem("anime_rag_user_id");
  if (!id) {
    id =
      window.crypto?.randomUUID?.() ||
      "u-" + Math.random().toString(36).slice(2);
    localStorage.setItem("anime_rag_user_id", id);
  }
  return id;
}

function textOn(hex) {
  if (!hex || hex.length < 7) return "#fff";
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#10131a" : "#fff";
}

const srcUrl = (rec) => rec?.sources?.[0]?.url || null;

export default function Home() {
  const [userId, setUserId] = useState(null);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [recs, setRecs] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");

  // AniList auth
  const [token, setToken] = useState(null);
  const [viewer, setViewer] = useState(null);
  const [watchedIds, setWatchedIds] = useState(() => new Set());
  const [hideWatched, setHideWatched] = useState(false);

  // Engagement
  const [savedRecs, setSavedRecs] = useState([]);
  const [savedUrls, setSavedUrls] = useState(() => new Set());
  const [votes, setVotes] = useState({}); // url -> 1 | -1
  const [view, setView] = useState("search"); // "search" | "saved"
  const [toast, setToast] = useState("");

  useEffect(() => {
    // Pre-warm the backend (free Render instances sleep when idle) so it's
    // awake by the time the user runs their first search.
    fetch(`${API}/health`).catch(() => {});

    const id = getUserId();
    setUserId(id);
    loadEngagement(id);

    const fresh = readTokenFromHash();
    const t = fresh || localStorage.getItem("anilist_token");
    if (t) {
      setToken(t);
      localStorage.setItem("anilist_token", t);
      const cu = localStorage.getItem("anilist_user");
      const ci = localStorage.getItem("anilist_watched_ids");
      const cp = localStorage.getItem("anilist_profile");
      if (cu) setViewer(JSON.parse(cu));
      if (ci) setWatchedIds(new Set(JSON.parse(ci)));
      if (cp) setProfile(JSON.parse(cp));
      if (fresh || !cp) linkAniList(t, id);
    } else {
      loadProfile(id);
    }

    // Deep link: /?q=... reproduces a search
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) {
      setQuery(q);
      search(q, id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Count up while a search is in flight (free Voyage tier is slow ~1 min).
  useEffect(() => {
    if (!loading) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  function notify(msg) {
    setToast(msg);
    window.clearTimeout(notify._t);
    notify._t = window.setTimeout(() => setToast(""), 1900);
  }

  async function loadProfile(id) {
    try {
      const res = await fetch(`${API}/prefs?user_id=${encodeURIComponent(id)}`);
      if (res.ok) setProfile(await res.json());
    } catch {
      /* best-effort */
    }
  }

  async function loadEngagement(id) {
    try {
      const [s, f] = await Promise.all([
        fetch(`${API}/saves?user_id=${encodeURIComponent(id)}`).then((r) => r.json()),
        fetch(`${API}/feedback?user_id=${encodeURIComponent(id)}`).then((r) => r.json()),
      ]);
      setSavesFromList(s.saves || []);
      setVotes(f.votes || {});
    } catch {
      /* best-effort */
    }
  }

  function setSavesFromList(list) {
    setSavedRecs(list);
    setSavedUrls(new Set(list.map(srcUrl).filter(Boolean)));
  }

  async function linkAniList(t, id) {
    try {
      const v = await fetchViewer(t);
      setViewer(v);
      localStorage.setItem("anilist_user", JSON.stringify(v));
      const completed = await fetchCompleted(t, v.id);
      const ids = completed.map((c) => c.id);
      setWatchedIds(new Set(ids));
      localStorage.setItem("anilist_watched_ids", JSON.stringify(ids));
      const sample = [...completed]
        .sort((a, b) => b.score - a.score)
        .slice(0, 40)
        .map((c) => ({ title: c.title, genres: c.genres }));
      const res = await fetch(`${API}/prefs/seed`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ user_id: id, watched: sample }),
      });
      if (res.ok) {
        const p = await res.json();
        setProfile(p);
        localStorage.setItem("anilist_profile", JSON.stringify(p));
      }
    } catch (e) {
      console.warn("AniList link failed:", e.message);
      logout();
    }
  }

  function logout() {
    setToken(null);
    setViewer(null);
    setWatchedIds(new Set());
    setHideWatched(false);
    ["anilist_token", "anilist_user", "anilist_watched_ids", "anilist_profile"].forEach(
      (k) => localStorage.removeItem(k)
    );
    if (userId) loadProfile(userId);
  }

  async function search(q, uidOverride) {
    const uid = uidOverride || userId;
    const text = (q ?? query).trim();
    if (!text || loading) return;
    setView("search");
    setQuery(text);
    setActiveQuery(text);
    setLoading(true);
    setError("");
    setRecs(null);
    try {
      const res = await fetch(`${API}/recommend`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: text, user_id: uid }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Request failed (${res.status})`);
      }
      setRecs(await res.json());
      if (!token) loadProfile(uid);
    } catch (e) {
      setError(
        e.message?.includes("Failed to fetch")
          ? `Could not reach the API at ${API}. Is the backend running?`
          : e.message
      );
    } finally {
      setLoading(false);
    }
  }

  async function toggleSave(rec) {
    const url = srcUrl(rec);
    if (!url) return;
    const saved = savedUrls.has(url);
    try {
      const res = await fetch(`${API}/saves${saved ? "/delete" : ""}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(saved ? { user_id: userId, anime_url: url } : { user_id: userId, rec }),
      });
      const data = await res.json();
      setSavesFromList(data.saves || []);
      notify(saved ? "Removed from saved" : "Saved ♥");
    } catch {
      notify("Couldn't update saved");
    }
  }

  async function vote(rec, v) {
    const url = srcUrl(rec);
    if (!url) return;
    const next = votes[url] === v ? 0 : v;
    try {
      const res = await fetch(`${API}/feedback`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          anime_url: url,
          vote: next,
          title: rec.title,
          genres: rec.sources?.[0]?.genres || [],
        }),
      });
      const data = await res.json();
      setVotes(data.votes || {});
      if (next === 1) notify("Thanks — more like this 👍");
      else if (next === -1) notify("Got it — fewer like this 👎");
    } catch {
      notify("Couldn't record vote");
    }
  }

  async function share(rec) {
    const link = activeQuery
      ? `${window.location.origin}/?q=${encodeURIComponent(activeQuery)}`
      : srcUrl(rec);
    try {
      await navigator.clipboard.writeText(link);
      notify("Link copied — reproduces this search");
    } catch {
      notify("Copy failed — link: " + link);
    }
  }

  const hasProfile = profile && profile.attributes?.length > 0;
  const fromAniList = profile?.source === "anilist";
  const cardHandlers = { onToggleSave: toggleSave, onVote: vote, onShare: share };

  return (
    <main className="wrap">
      <header className="top">
        <h1 className="brand">
          Anime<span className="accent">RAG</span>
        </h1>
        <div className="auth">
          {(savedUrls.size > 0 || view === "saved") && (
            <button
              className="saved-toggle"
              onClick={() => setView((v) => (v === "saved" ? "search" : "saved"))}
            >
              {view === "saved" ? "← Search" : `♥ Saved ${savedUrls.size}`}
            </button>
          )}
          {viewer ? (
            <div className="viewer">
              {viewer.avatar?.medium && (
                <img className="avatar" src={viewer.avatar.medium} alt="" />
              )}
              <span className="viewer-name">{viewer.name}</span>
              <button className="link-btn" onClick={logout}>
                Log out
              </button>
            </div>
          ) : CLIENT_ID ? (
            <a className="anilist-btn" href={loginUrl()}>
              Link AniList
            </a>
          ) : null}
        </div>
      </header>

      <p className="tagline">
        Tell me your taste in plain English. Every pick is grounded in a real
        source — no made-up recommendations.
      </p>

      {hasProfile && (
        <div className="taste-banner">
          <span className="taste-label">
            {fromAniList ? "From your AniList history" : "Your taste"}
          </span>
          <span className="taste-tags">
            {profile.attributes.map((a, i) => (
              <span key={a}>
                {i > 0 && <span className="dot"> · </span>}
                {a}
              </span>
            ))}
          </span>
        </div>
      )}

      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. slow burn political thriller, I don't care about action"
          aria-label="Search query"
        />
        <button type="submit" disabled={loading || !query.trim()}>
          {loading ? <span className="spinner" /> : "Recommend"}
        </button>
      </form>

      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            className={"chip" + (activeQuery === ex ? " active" : "")}
            type="button"
            onClick={() => search(ex)}
            disabled={loading}
          >
            {ex}
          </button>
        ))}
      </div>

      {view === "saved" ? (
        <SavedList recs={savedRecs} votes={votes} {...cardHandlers} />
      ) : (
        <>
          {error && !loading && (
            <ErrorState message={error} onRetry={() => search(activeQuery)} />
          )}
          {loading && <LoadingSkeleton elapsed={elapsed} />}
          {recs && !loading && (
            <Results
              data={recs}
              watchedIds={watchedIds}
              loggedIn={!!token}
              hideWatched={hideWatched}
              onToggleHide={() => setHideWatched((v) => !v)}
              onExample={(q) => search(q)}
              savedUrls={savedUrls}
              votes={votes}
              {...cardHandlers}
            />
          )}
        </>
      )}

      {toast && <div className="toast">{toast}</div>}

      <div className="footer">
        Grounded in AniList · embeddings &amp; reranking by Voyage · written by
        Claude. {userId ? `Session: ${userId.slice(0, 8)}…` : ""}
      </div>
    </main>
  );
}

function LoadingSkeleton({ elapsed = 0 }) {
  return (
    <div>
      <div className="searching">
        <span className="spinner dark" />
        <span>
          Searching sources &amp; reasoning… {elapsed}s
          <span className="searching-note">
            {" "}
            — embeddings &amp; reranking run on a rate-limited free tier, so this
            can take up to ~1 minute.
          </span>
        </span>
      </div>
      {[0, 1, 2].map((i) => (
        <div className="card skeleton" key={i}>
          <div className="sk sk-cover" />
          <div className="card-body">
            <div className="sk sk-line w60" />
            <div className="sk sk-pills" />
            <div className="sk sk-line w100" />
            <div className="sk sk-line w90" />
            <div className="sk sk-line w40" />
          </div>
        </div>
      ))}
    </div>
  );
}

function Results({
  data,
  watchedIds,
  loggedIn,
  hideWatched,
  onToggleHide,
  onExample,
  savedUrls,
  votes,
  onToggleSave,
  onVote,
  onShare,
}) {
  if (!data.grounded || data.recs.length === 0) {
    return <EmptyState message={data.message} onExample={onExample} />;
  }
  const marked = data.recs.map((rec) => {
    const id = anilistIdFromUrl(rec.sources[0]?.url);
    return { rec, watched: id != null && watchedIds.has(id) };
  });
  const watchedCount = marked.filter((m) => m.watched).length;
  const shown = hideWatched ? marked.filter((m) => !m.watched) : marked;

  return (
    <div>
      {loggedIn && watchedCount > 0 && (
        <label className="hide-toggle">
          <input type="checkbox" checked={hideWatched} onChange={onToggleHide} />
          Hide {watchedCount} already-watched
        </label>
      )}
      {shown.length === 0 ? (
        <div className="note">
          All {watchedCount} recommendations are ones you&apos;ve already watched
          — uncheck the toggle to see them.
        </div>
      ) : (
        shown.map(({ rec, watched }, i) => (
          <RecCard
            key={i}
            rec={rec}
            index={i}
            watched={watched}
            saved={savedUrls.has(rec.sources[0]?.url)}
            vote={votes[rec.sources[0]?.url]}
            onToggleSave={onToggleSave}
            onVote={onVote}
            onShare={onShare}
          />
        ))
      )}
    </div>
  );
}

function SavedList({ recs, votes, onToggleSave, onVote, onShare }) {
  if (!recs.length) {
    return (
      <div className="state-card">
        <div className="state-emoji">♡</div>
        <h3>No saved shows yet</h3>
        <p>Tap the heart on any recommendation to keep it here for later.</p>
      </div>
    );
  }
  return (
    <div>
      {recs.map((rec, i) => (
        <RecCard
          key={i}
          rec={rec}
          index={i}
          watched={false}
          saved={true}
          vote={votes[rec.sources[0]?.url]}
          onToggleSave={onToggleSave}
          onVote={onVote}
          onShare={onShare}
        />
      ))}
    </div>
  );
}

function EmptyState({ message, onExample }) {
  return (
    <div className="state-card">
      <div className="state-emoji">🔍</div>
      <h3>No grounded match for that one</h3>
      <p>
        {message ||
          "Nothing in the library was a confident fit. Try describing a vibe, a show you liked, or a mood — the more specific, the better."}
      </p>
      <div className="state-suggests">
        {["dark psychological thriller", "wholesome slice of life", "epic fantasy adventure"].map(
          (s) => (
            <button key={s} className="chip" onClick={() => onExample(s)}>
              {s}
            </button>
          )
        )}
      </div>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  const isRate = /too many|limit reached/i.test(message);
  return (
    <div className="state-card error-card">
      <div className="state-emoji">{isRate ? "⏳" : "⚠️"}</div>
      <h3>{isRate ? "Easy there" : "Something went wrong"}</h3>
      <p>{message}</p>
      {!isRate && (
        <button className="retry-btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

function RecCard({ rec, index, watched, saved, vote, onToggleSave, onVote, onShare }) {
  const [showWhy, setShowWhy] = useState(false);
  const primary = rec.sources[0] || {};
  const score = primary.score != null ? (primary.score / 10).toFixed(1) : null;
  const metaBits = [
    primary.episodes ? `${primary.episodes} eps` : null,
    primary.year || null,
  ].filter(Boolean);

  return (
    <article
      className={"card" + (watched ? " is-watched" : "")}
      style={{ animationDelay: `${index * 90}ms` }}
    >
      {primary.cover_image && (
        <img className="cover" src={primary.cover_image} alt={rec.title} loading="lazy" />
      )}
      <div className="card-body">
        <div className="card-head">
          <h3>{rec.title}</h3>
          <div className="head-right">
            {watched && <span className="watched-badge">✓ Watched</span>}
            {score && <span className="score">⭐ {score}</span>}
          </div>
        </div>

        {primary.genres?.length > 0 && (
          <div className="genres">
            {primary.genres.map((g) => (
              <span className="genre" key={g}>
                {g}
              </span>
            ))}
          </div>
        )}

        {metaBits.length > 0 && <div className="meta-line">{metaBits.join(" · ")}</div>}

        <p>{rec.reasoning}</p>

        <div className="sources">
          <span className="src-label">Source</span>
          {rec.sources.map((s, j) => (
            <a
              key={j}
              className="source-link"
              href={s.url}
              target="_blank"
              rel="noreferrer"
            >
              {s.anime_title} ↗
            </a>
          ))}
        </div>

        {primary.streaming?.length > 0 && (
          <div className="streaming">
            <span className="src-label">Watch on</span>
            {primary.streaming.map((st, k) => (
              <a
                key={k}
                className="stream-pill"
                href={st.url}
                target="_blank"
                rel="noreferrer"
                style={{ background: st.color || "#3a4150", color: textOn(st.color) }}
              >
                {st.site}
              </a>
            ))}
          </div>
        )}

        <div className="card-actions">
          <button
            className={"act" + (saved ? " on" : "")}
            onClick={() => onToggleSave(rec)}
          >
            {saved ? "♥" : "♡"} {saved ? "Saved" : "Save"}
          </button>
          <button
            className={"act icon" + (vote === 1 ? " up" : "")}
            onClick={() => onVote(rec, 1)}
            title="Good rec"
          >
            👍
          </button>
          <button
            className={"act icon" + (vote === -1 ? " down" : "")}
            onClick={() => onVote(rec, -1)}
            title="Bad rec"
          >
            👎
          </button>
          <button className="act" onClick={() => onShare(rec)}>
            ↗ Share
          </button>
        </div>

        {primary.chunk_text && (
          <div className="why">
            <button
              className="why-toggle"
              onClick={() => setShowWhy((v) => !v)}
              aria-expanded={showWhy}
            >
              {showWhy ? "▾" : "▸"} Why this rec?
            </button>
            {showWhy && (
              <div className="why-panel">
                <div className="why-meta">
                  Retrieved chunk this rec is grounded in
                  {primary.rerank_score != null &&
                    ` · relevance ${primary.rerank_score.toFixed(3)}`}
                </div>
                <pre className="chunk">{primary.chunk_text}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
