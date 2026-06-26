"""Group anime into franchises from AniList `relations`, so the recommender can
avoid suggesting a named show's own seasons/sequels.

Two jobs, both computed from data/anime.json at request time (no vector-store
changes, so growing this map never requires re-embedding):

- `franchise_of(url)`  — which franchise a candidate belongs to, used to (a) drop
  candidates from a franchise the user explicitly named and (b) collapse multiple
  entries of the same franchise (e.g. AOT S1 + Final Season) to one rec.
- `referenced_franchises(query)` — franchises whose title appears in the query
  text, i.e. the shows the user is asking to be matched *against*, not handed back.

Franchises are connected components over SEQUEL/PREQUEL/SIDE_STORY/PARENT/
ALTERNATIVE/SPIN_OFF edges (union-find). Edges to shows outside the corpus still
link two in-corpus shows that share a common relative (e.g. two side stories of a
parent we don't index).
"""
import json
import re
from functools import lru_cache

from app import config

_NORM_RE = re.compile(r"[^a-z0-9]+")
# Trailing season/part/movie markers — stripped so "Attack on Titan Season 2"
# also yields the base alias "attack on titan".
_SUFFIX_RE = re.compile(
    r"\s+(season|part|cour|movie|film|the\s+movie|"
    r"\d+|[ivx]+|i{1,3})(\s+\d+)?$",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return _NORM_RE.sub(" ", s.lower()).strip()


def _aliases(title: str) -> set[str]:
    """Short forms a user might type: the full title, the part before a
    subtitle separator, and those with trailing season/part markers removed."""
    out: set[str] = set()
    # split off subtitles after :, -, ~, (, etc. and take the leading segment too
    lead = re.split(r"[:\-–—~(]", title, maxsplit=1)[0]
    for raw in (title, lead):
        prev = None
        cur = raw
        while cur and cur != prev:  # strip stacked markers ("... Season 3 Part 2")
            prev = cur
            cur = _SUFFIX_RE.sub("", cur).strip()
        for v in (raw, cur):
            n = _norm(v)
            # 2+ words, or a single word of >=5 chars, to avoid matching common
            # short words inside ordinary queries.
            if n and (" " in n or len(n) >= 5):
                out.add(n)
    return out


def _node_key(show: dict) -> str:
    mal = show.get("mal_id")
    return f"mal:{mal}" if mal else f"title:{_norm(show.get('title', ''))}"


@lru_cache(maxsize=1)
def _index() -> dict:
    """Build url->franchise and (normalized title, franchise) from anime.json."""
    if not config.ANIME_JSON.exists():
        return {"url_to_fr": {}, "title_fr": []}
    shows = json.loads(config.ANIME_JSON.read_text())

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path-compress
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for show in shows:
        key = _node_key(show)
        find(key)
        for rel in show.get("relations", []):
            rmal = rel.get("mal_id")
            if rmal:
                union(key, f"mal:{rmal}")

    url_to_fr: dict[str, str] = {}
    alias_fr: list[tuple[str, str]] = []
    fr_rep: dict[str, str] = {}  # franchise -> flagship url (first in popularity order)
    for show in shows:
        fr = find(_node_key(show))
        url = show.get("url")
        if url:
            url_to_fr[url] = fr
            # anime.json is popularity-desc, so the first url seen for a franchise
            # is its flagship entry (e.g. "Attack on Titan", not "... Season 3").
            fr_rep.setdefault(fr, url)
        for alias in _aliases(show.get("title", "")):
            alias_fr.append((alias, fr))
    return {"url_to_fr": url_to_fr, "alias_fr": alias_fr, "fr_rep": fr_rep}


def franchise_of(url: str) -> str | None:
    return _index()["url_to_fr"].get(url)


def representative_of(url: str) -> str:
    """The flagship in-corpus entry of this url's franchise (the popular base
    title, not a specific season). Falls back to the url itself if unknown."""
    idx = _index()
    fr = idx["url_to_fr"].get(url)
    return idx["fr_rep"].get(fr, url) if fr is not None else url


def referenced_franchises(query: str) -> set[str]:
    """Franchises whose title (or a short alias) appears as a whole phrase in the query."""
    padded = f" {_norm(query)} "
    return {fr for alias, fr in _index()["alias_fr"] if f" {alias} " in padded}
