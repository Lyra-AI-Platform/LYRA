"""X (Twitter) through the official API, only when X_BEARER_TOKEN is set.

What it does, matching the use case given to X:
- Reads new posts from the official X accounts of people on the watchlist (accounts from
  Wikidata), shown on lyraauth.com with a link back to X.
- Keeps X content for at most X_RETENTION_HOURS and only inside the site: it is left out of
  the public JSON feed, the per-person JSON and llms.txt (X's terms forbid redistribution).
- Never reads, stores or shows other users' posts, and infers nothing about anyone.

Budget: X plans cap how many posts an app may read a month. Every post received is counted
and reading stops at X_MONTHLY_POST_CAP; rate-limit replies pause that endpoint until X's
reset time.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from lyra.watch.config import WATCH_DIR

logger = logging.getLogger(__name__)

API = "https://api.x.com/2"
STATE_FILE = WATCH_DIR / "x_state.json"
RETENTION_HOURS = float(os.environ.get("X_RETENTION_HOURS", 24))
MONTHLY_CAP = int(os.environ.get("X_MONTHLY_POST_CAP", 10000))
PER_REQUEST = 5   # newest posts asked for per account per check
# Each account is checked at most this often, keeping ~40 accounts inside Basic-plan rate limits.
CHECK_MINUTES = float(os.environ.get("X_CHECK_MINUTES", 30))


def enabled() -> bool:
    return bool(os.environ.get("X_BEARER_TOKEN"))


def _load() -> Dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"ids": {}, "since": {}, "month": "", "used": 0, "paused_until": 0}


def _save(state: Dict):
    try:
        STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def status() -> Dict:
    if not enabled():
        return {"on": False, "detail": "off (no X_BEARER_TOKEN)"}
    st = _load()
    used = st["used"] if st.get("month") == _month() else 0
    return {"on": True, "posts_read_this_month": used, "monthly_cap": MONTHLY_CAP,
            "paused": st.get("paused_until", 0) > time.time(), "accounts_resolved": len(st.get("ids", {})),
            "last_error": st.get("last_error")}


async def _get(path: str, params: Dict, state: Dict) -> Optional[Dict]:
    """One API call; honours rate limits and the monthly budget."""
    if state.get("paused_until", 0) > time.time():
        return None
    if state.get("month") != _month():
        state.update(month=_month(), used=0)
    if state["used"] >= MONTHLY_CAP:
        state["last_error"] = "monthly post cap reached"
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{API}{path}", params=params,
                                    headers={"Authorization": f"Bearer {os.environ['X_BEARER_TOKEN']}",
                                             "User-Agent": "LyraWatch/1.0"})
    except httpx.HTTPError as e:
        state["last_error"] = f"network: {e.__class__.__name__}"
        return None
    if resp.status_code == 429:
        reset = float(resp.headers.get("x-rate-limit-reset", time.time() + 900))
        state.update(paused_until=reset, last_error="rate limited")
        return None
    if resp.status_code in (401, 403):
        # Bad token, or an endpoint the plan doesn't include: stop for an hour rather than hammering.
        state.update(paused_until=time.time() + 3600, last_error=f"{resp.status_code}: {resp.text[:120]}")
        return None
    if resp.status_code != 200:
        state["last_error"] = f"HTTP {resp.status_code}"
        return None
    state.pop("last_error", None)
    return resp.json()


async def resolve(usernames: List[str], state: Dict) -> Dict[str, str]:
    """username (lower case) -> user id, looked up once and remembered."""
    wanted = [u for u in dict.fromkeys(u.lower() for u in usernames) if u not in state["ids"]]
    for i in range(0, len(wanted), 100):
        data = await _get("/users/by", {"usernames": ",".join(wanted[i:i + 100])}, state)
        for u in (data or {}).get("data", []):
            state["ids"][u["username"].lower()] = u["id"]
    return state["ids"]


async def new_posts(person: Dict, usernames: List[str]) -> List[Dict]:
    """New original posts (no replies or reposts) from the person's X accounts since the last check,
    as feed items. The first check of an account only records where it is."""
    if not enabled() or not usernames:
        return []
    state = _load()
    ids = await resolve(usernames, state)
    items = []
    for name in usernames:
        uid = ids.get(name.lower())
        if not uid or time.time() - state.setdefault("checked", {}).get(uid, 0) < CHECK_MINUTES * 60:
            continue
        state["checked"][uid] = time.time()
        params = {"max_results": PER_REQUEST, "exclude": "replies,retweets", "tweet.fields": "created_at,public_metrics"}
        first = uid not in state["since"]
        if not first:
            params["since_id"] = state["since"][uid]
        data = await _get(f"/users/{uid}/tweets", params, state)
        posts = (data or {}).get("data", [])
        state["used"] += len(posts)
        if posts:
            state["since"][uid] = max(posts, key=lambda p: int(p["id"]))["id"]
        if first:
            continue
        for p in posts:
            text = " ".join(p.get("text", "").split())
            items.append({"title": text if len(text) <= 240 else text[:237].rsplit(" ", 1)[0] + "…",
                          "url": f"https://x.com/{name}/status/{p['id']}", "source": f"X @{name}", "summary": "",
                          "published": _ts(p.get("created_at")), "own_words": True, "platform": "X", "x": True,
                          "metrics": p.get("public_metrics", {})})
    _save(state)
    return items


def _ts(s: Optional[str]) -> float:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def expired(event: Dict) -> bool:
    """X content older than the retention window is dropped from the live history."""
    return bool(event.get("x")) and time.time() - event.get("ts", 0) > RETENTION_HOURS * 3600
