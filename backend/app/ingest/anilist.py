"""Fetch popular anime from the AniList GraphQL API (no auth) into data/anime.json.

Usage:
    python -m app.ingest.anilist            # fetches ~120 shows
    python -m app.ingest.anilist --target 200
"""
import argparse
import html
import json
import re
import sys
import time

import httpx

from app import config

ANILIST_URL = "https://graphql.anilist.co"
PER_PAGE = 50  # AniList max

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage currentPage }
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false) {
      idMal
      title { romaji english }
      description(asHtml: false)
      genres
      averageScore
      episodes
      seasonYear
      startDate { year }
      coverImage { large medium }
      externalLinks { site url type color }
      tags { name rank isGeneralSpoiler }
      relations { edges { relationType node { idMal type } } }
      siteUrl
    }
  }
}
"""

_TAG_RE = re.compile(r"<[^>]+>")

# Relations that put two shows in the SAME franchise — used downstream to avoid
# recommending a named show's own sequels/seasons. ADAPTATION/SOURCE/CHARACTER
# (manga, light novels, shared voice actors) are intentionally excluded.
FRANCHISE_RELATIONS = {
    "SEQUEL", "PREQUEL", "SIDE_STORY", "PARENT",
    "ALTERNATIVE", "SPIN_OFF", "SUMMARY", "FULL_STORY",
}


def clean_text(text: str | None) -> str:
    """Strip residual HTML/markup and collapse whitespace from a synopsis."""
    if not text:
        return ""
    text = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def pick_title(title: dict) -> str:
    return title.get("english") or title.get("romaji") or "Unknown"


def normalize(media: dict) -> dict:
    tags = [
        t["name"]
        for t in (media.get("tags") or [])
        if t.get("rank", 0) >= 60 and not t.get("isGeneralSpoiler")
    ][:8]
    cover = media.get("coverImage") or {}
    streaming = [
        {"site": link["site"], "url": link["url"], "color": link.get("color")}
        for link in (media.get("externalLinks") or [])
        if link.get("type") == "STREAMING" and link.get("site") and link.get("url")
    ][:6]
    year = media.get("seasonYear") or (media.get("startDate") or {}).get("year") or 0
    relations = [
        {"mal_id": edge["node"]["idMal"], "type": edge["relationType"]}
        for edge in ((media.get("relations") or {}).get("edges") or [])
        if edge.get("relationType") in FRANCHISE_RELATIONS
        and edge.get("node")
        and edge["node"].get("type") == "ANIME"
        and edge["node"].get("idMal")
    ]
    return {
        "mal_id": media.get("idMal") or 0,
        "title": pick_title(media.get("title") or {}),
        "synopsis": clean_text(media.get("description")),
        "genres": media.get("genres") or [],
        "tags": tags,
        "score": media.get("averageScore") or 0,
        "episodes": media.get("episodes") or 0,
        "year": year,
        "cover_image": cover.get("large") or cover.get("medium") or "",
        "streaming": streaming,
        "relations": relations,
        "url": media.get("siteUrl") or "",
    }


def fetch(target: int = 120) -> list[dict]:
    """Page through AniList until we have >= target shows with a synopsis."""
    out: list[dict] = []
    page = 1
    with httpx.Client(timeout=30) as client:
        while len(out) < target:
            resp = client.post(
                ANILIST_URL,
                json={"query": QUERY, "variables": {"page": page, "perPage": PER_PAGE}},
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5"))
                print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()["data"]["Page"]
            for media in data["media"]:
                rec = normalize(media)
                if rec["synopsis"]:  # skip shows with no usable text
                    out.append(rec)
            print(f"  page {page}: total {len(out)}")
            if not data["pageInfo"]["hasNextPage"]:
                break
            page += 1
            time.sleep(0.8)  # be polite to the public API
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=120)
    args = parser.parse_args()

    shows = fetch(args.target)
    config.ANIME_JSON.write_text(json.dumps(shows, ensure_ascii=False, indent=2))
    print(f"Wrote {len(shows)} shows -> {config.ANIME_JSON}")
    if len(shows) < 100:
        print("WARNING: fewer than 100 shows fetched.", file=sys.stderr)


if __name__ == "__main__":
    main()
