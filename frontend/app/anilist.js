// AniList OAuth (implicit grant) + GraphQL helpers, run entirely in the browser.
// The access token never touches our backend — only a sample of watched
// titles+genres is sent there for taste inference.

const ANILIST_GQL = "https://graphql.anilist.co";
export const CLIENT_ID = process.env.NEXT_PUBLIC_ANILIST_CLIENT_ID || "";

export function loginUrl() {
  // response_type=token => AniList returns the token in the URL fragment,
  // redirecting to the redirect URL registered on the API client.
  return `https://anilist.co/api/v2/oauth/authorize?client_id=${CLIENT_ID}&response_type=token`;
}

// Pull #access_token=... out of the URL fragment after the OAuth redirect.
export function readTokenFromHash() {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  if (!hash.includes("access_token")) return null;
  const token = new URLSearchParams(hash.slice(1)).get("access_token");
  if (token) {
    history.replaceState(null, "", window.location.pathname); // strip token from URL
  }
  return token;
}

async function gql(query, token, variables) {
  const res = await fetch(ANILIST_GQL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query, variables }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || json.errors) {
    throw new Error(json.errors?.[0]?.message || `AniList error ${res.status}`);
  }
  return json.data;
}

export async function fetchViewer(token) {
  const data = await gql(`query { Viewer { id name avatar { medium } } }`, token);
  return data.Viewer;
}

export async function fetchCompleted(token, anilistUserId) {
  const query = `
    query ($userId: Int) {
      MediaListCollection(userId: $userId, type: ANIME, status: COMPLETED) {
        lists {
          entries {
            score(format: POINT_10)
            media { id genres title { romaji english } }
          }
        }
      }
    }`;
  const data = await gql(query, token, { userId: anilistUserId });
  const entries = (data.MediaListCollection?.lists || []).flatMap(
    (l) => l.entries || []
  );
  return entries.map((e) => ({
    id: e.media.id,
    title: e.media.title.english || e.media.title.romaji,
    genres: e.media.genres || [],
    score: e.score || 0,
  }));
}

// AniList id embedded in a source URL like https://anilist.co/anime/16498
export function anilistIdFromUrl(url) {
  const m = /anilist\.co\/anime\/(\d+)/.exec(url || "");
  return m ? Number(m[1]) : null;
}
