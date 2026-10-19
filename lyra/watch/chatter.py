"""More of what's said about a person, from sources that allow it:

- GDELT: a free global news index, updated every 15 minutes, far wider than Google News.
- Apple Podcasts search: recent episodes featuring the person (interviews).
- Hacker News (Algolia API) and Bluesky's public API: how much people are discussing them
  right now, and the tone. Only counts, tone and links to threads are kept; ordinary users'
  posts and names aren't republished.
- Reddit, only with approved API credentials (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET). Reddit's
  robots.txt disallows all crawling and its terms require approval for commercial use, so there
  is no scraping fallback.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import quote, quote_plus

import httpx

from lyra.market import sentiment
from lyra.market.config import SEC_USER_AGENT
from lyra.market.fetch import fetch_text

logger = logging.getLogger(__name__)

GDELT = ("https://api.gdeltproject.org/api/v2/doc/doc?query={q}%20sourcelang:english&mode=artlist&format=json"
         "&timespan={hours}h&maxrecords=50&sort=datedesc")
PODCASTS = "https://itunes.apple.com/search?term={q}&entity=podcastEpisode&limit=25"
HN = "https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=(story,comment)&numericFilters=created_at_i>{since}&hitsPerPage=100"
BLUESKY = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q={q}&limit=100&sort=latest&since={since}"
HN_ITEM = "https://news.ycombinator.com/item?id={id}"

# Headlines that are interviews, podcasts, speeches or press conferences.
INTERVIEW = re.compile(
    r"\binterview(?:ed|s)?\b|\bpodcast\b|\bsat down with\b|\bsits down with\b|\bin conversation with\b|\bkeynote\b|"
    r"\bspeech\b|\btold reporters\b|\bpress conference\b|\bfireside chat\b|\bQ&A\b|\btalks to\b|\bspeaks to\b|"
    r"\bon (?:CNBC|CNN|Fox|BBC|MSNBC|Sky News|Bloomberg TV|60 Minutes|Meet the Press|Face the Nation)\b", re.I)


def is_interview(title: str) -> bool:
    return bool(INTERVIEW.search(title or ""))


def _name(person: Dict) -> str:
    return re.sub(r"\s*\(.*?\)", "", person["name"]).strip()


def _gdelt_time(s: str) -> float:
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


# GDELT allows one request every 5 seconds per address. Every caller (the refresh and the live
# loop) shares this gate, and a refusal pauses GDELT for a minute.
GDELT_INTERVAL = 6.0
_gdelt_gate = asyncio.Lock()
_gdelt_state = {"next": 0.0, "refusals": 0, "last_ok": None, "articles": 0}


def gdelt_status() -> Dict:
    """For the health check: when GDELT last answered and whether it's currently backing off."""
    return {"last_ok": _gdelt_state["last_ok"], "refusals_in_a_row": _gdelt_state["refusals"],
            "backing_off": _gdelt_state["next"] - time.time() > GDELT_INTERVAL,
            "articles_last_answer": _gdelt_state["articles"]}


async def gdelt(person: Dict, hours: int = 24, max_age: float = 900) -> List[Dict]:
    """Recent English-language articles that mention the person, as feed items."""
    url = GDELT.format(q=quote(f'"{_name(person)}"'), hours=hours)
    async with _gdelt_gate:
        wait = _gdelt_state["next"] - time.time()
        if wait > 30:
            return []  # backing off after a refusal; the next cycle tries again
        if wait > 0:
            await asyncio.sleep(wait)
        body = await fetch_text(url, max_age=max_age, timeout=40, headers={"User-Agent": SEC_USER_AGENT})
        refused = body is None or not body.lstrip().startswith("{")
        if refused:
            # 1, 2, 4 ... minutes, up to 30, so a blocked address recovers instead of being hammered.
            _gdelt_state["refusals"] += 1
            _gdelt_state["next"] = time.time() + min(1800, 60 * 2 ** (_gdelt_state["refusals"] - 1))
        else:
            _gdelt_state.update(refusals=0, last_ok=time.time(), next=time.time() + GDELT_INTERVAL)
    try:
        rows = json.loads(body).get("articles", []) if body else []
    except ValueError:
        return []  # GDELT answers rate limits with a plain-text notice
    _gdelt_state["articles"] = len(rows)
    return [{"title": a.get("title", "").strip(), "url": a["url"], "source": a.get("domain", ""),
             "summary": "", "published": _gdelt_time(a.get("seendate", "")), "own_words": False, "via": "GDELT"}
            for a in rows if a.get("url") and a.get("title")]


async def podcasts(person: Dict, days: int = 30) -> List[Dict]:
    """Podcast episodes from the last `days` with the person's name in the title or description."""
    name = _name(person)
    body = await fetch_text(PODCASTS.format(q=quote_plus(name)), max_age=6 * 3600)
    try:
        rows = json.loads(body).get("results", []) if body else []
    except ValueError:
        return []
    out, cutoff = [], time.time() - days * 86400
    for r in rows:
        when = _iso(r.get("releaseDate", ""))
        text = f"{r.get('trackName', '')} {r.get('description', '')}"
        if when < cutoff or name.lower() not in text.lower():
            continue
        out.append({"title": f"{r.get('trackName', '').strip()} — {r.get('collectionName', '').strip()}",
                    "url": r.get("trackViewUrl", ""), "source": "Apple Podcasts", "summary": "",
                    "published": when, "own_words": False, "interview": True, "platform": "Podcast"})
    return [o for o in out if o["url"]]


def _iso(s: str) -> float:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


async def _json(url: str, max_age: float) -> Optional[Dict]:
    body = await fetch_text(url, max_age=max_age, headers={"User-Agent": SEC_USER_AGENT})
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


async def discussion(person: Dict, hours: int = 24, max_age: float = 600) -> Dict:
    """How much the person is being discussed in the last `hours`, per platform, with tone.
    Threads (Hacker News stories, Reddit posts) are kept as links; individual posts aren't."""
    name = _name(person)
    since = int(time.time() - hours * 3600)
    out: Dict = {"hours": hours, "platforms": {}, "threads": []}

    hn = await _json(HN.format(q=quote(f'"{name}"'), since=since), max_age)
    if hn is not None:
        hits = hn.get("hits", [])
        texts = [h.get("comment_text") or h.get("title") or "" for h in hits]
        out["platforms"]["Hacker News"] = {"mentions": hn.get("nbHits", len(hits)), **_tone(texts)}
        for h in hits:
            if "story" in h.get("_tags", []) and h.get("title"):
                out["threads"].append({"platform": "Hacker News", "title": h["title"],
                                       "url": HN_ITEM.format(id=h["objectID"]), "score": h.get("points") or 0,
                                       "comments": h.get("num_comments") or 0,
                                       "published": float(h.get("created_at_i") or 0)})

    since_iso = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bsky = await _json(BLUESKY.format(q=quote(f'"{name}"'), since=since_iso), max_age)
    if bsky is not None:
        posts = bsky.get("posts", [])
        out["platforms"]["Bluesky"] = {"mentions": len(posts), "capped": len(posts) >= 100,
                                       **_tone([(p.get("record") or {}).get("text", "") for p in posts])}

    reddit_data = await reddit(name, hours)
    if reddit_data is not None:
        out["platforms"]["Reddit"] = reddit_data["summary"]
        out["threads"] += reddit_data["threads"]

    out["threads"].sort(key=lambda t: (t["score"] + 2 * t["comments"]), reverse=True)
    out["threads"] = out["threads"][:10]
    total = sum(p["mentions"] for p in out["platforms"].values())
    weighted = [(p["avg"], p["mentions"]) for p in out["platforms"].values() if p.get("mentions")]
    avg = sum(a * n for a, n in weighted) / max(sum(n for _, n in weighted), 1)
    out.update(total=total, tone={"avg": round(avg, 3), "label": _label(avg)}, checked_at=time.time())
    return out


def _label(avg: float) -> str:
    return "positive" if avg >= 0.15 else "negative" if avg <= -0.15 else "neutral"


def _tone(texts: List[str]) -> Dict:
    scores = [sentiment.score(t) for t in texts if t]
    avg = sum(scores) / len(scores) if scores else 0.0
    return {"avg": round(avg, 3), "label": _label(avg)}


# ── Reddit (approved API access only) ──────────────────────────────────────

_reddit_token: Dict = {}


def reddit_enabled() -> bool:
    return bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))


async def _reddit_auth() -> Optional[str]:
    if _reddit_token.get("expires", 0) > time.time() + 60:
        return _reddit_token["token"]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post("https://www.reddit.com/api/v1/access_token",
                                     data={"grant_type": "client_credentials"},
                                     auth=(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]),
                                     headers={"User-Agent": os.environ.get("REDDIT_USER_AGENT", SEC_USER_AGENT)})
        data = resp.json()
        _reddit_token.update(token=data["access_token"], expires=time.time() + data.get("expires_in", 3600))
        return _reddit_token["token"]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Reddit sign-in failed: {e}")
        return None


async def reddit(name: str, hours: int = 24) -> Optional[Dict]:
    """Posts mentioning the name in the last day, through Reddit's official API. None when Reddit
    isn't configured. Keeps titles, subreddits, scores and links; never usernames."""
    if not reddit_enabled():
        return None
    token = await _reddit_auth()
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get("https://oauth.reddit.com/search",
                                    params={"q": f'"{name}"', "sort": "new", "t": "day", "limit": 100, "type": "link"},
                                    headers={"Authorization": f"bearer {token}",
                                             "User-Agent": os.environ.get("REDDIT_USER_AGENT", SEC_USER_AGENT)})
        children = resp.json().get("data", {}).get("children", [])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Reddit search failed: {e}")
        return None
    cutoff = time.time() - hours * 3600
    posts = [c["data"] for c in children if c.get("data", {}).get("created_utc", 0) >= cutoff]
    threads = [{"platform": "Reddit", "title": p.get("title", ""), "subreddit": p.get("subreddit_name_prefixed", ""),
                "url": f"https://www.reddit.com{p.get('permalink', '')}", "score": p.get("score", 0),
                "comments": p.get("num_comments", 0), "published": float(p.get("created_utc", 0))}
               for p in posts if not p.get("over_18")]
    return {"summary": {"mentions": len(posts), "comments": sum(p.get("num_comments", 0) for p in posts),
                        **_tone([p.get("title", "") for p in posts])},
            "threads": threads}
