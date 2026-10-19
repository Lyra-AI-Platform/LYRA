"""
Lyra Watch API — public figures' disclosed trades, power moves and statements.

Read-only and public: everything comes from public records and is rebuilt in the
background, so requests only read stored profiles. Rate limited per IP.
"""
import asyncio
import hmac
import json
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from lyra.api.entitlements import require_paid
from lyra.db.models import User
from lyra.watch import live, service
from lyra.watch.config import CATEGORIES, load_roster

READS_PER_HOUR = 600
_hits: Dict[str, Deque[float]] = defaultdict(deque)

router = APIRouter(prefix="/api/watch", tags=["watch"])


def _public(response: Response, request: Request):
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= READS_PER_HOUR:
        raise HTTPException(429, "Rate limit reached. Try again later.")
    q.append(now)
    response.headers["Cache-Control"] = "public, max-age=300"


@router.get("/figures")
async def figures(response: Response, request: Request, category: str = ""):
    _public(response, request)
    roster = [p for p in load_roster() if not category or p.get("category") == category]
    index = service.load_people()
    return {"categories": CATEGORIES, "figures": [service.card(p, index) for p in roster]}


@router.get("/figures/{slug}")
async def figure(slug: str, response: Response, request: Request):
    _public(response, request)
    person = next((p for p in load_roster() if p["slug"] == slug), None)
    if not person:
        raise HTTPException(404, "Not on the watchlist")
    return service.load_profile(slug) or {**service.card(person), "pending": True}


@router.get("/people")
async def people(response: Response, request: Request, q: str = "", watched: str = "", limit: int = 100):
    """Everyone named in the coverage: job, linked companies, tone and a popularity rating."""
    _public(response, request)
    flag = {"": None, "true": True, "false": False}.get(watched.lower())
    return service.people_list(q[:80], flag, min(max(limit, 1), 500))


@router.get("/people/{pid}")
async def person(pid: str, response: Response, request: Request):
    """One person as JSON: job, popularity, documented politics, interests, companies, recent headlines.
    Stable URL, meant for linking and for AI agents."""
    _public(response, request)
    rec = service.person_record(pid[:120])
    if not rec:
        raise HTTPException(404, "No public figure with that id")
    return {**rec, "links": _links(rec)}


def _links(rec):
    base = "https://lyraauth.com"
    return {"self": f"{base}/api/watch/people/{rec['id']}",
            "page": f"{base}/watch/#person/{rec['id']}",
            "profile": f"{base}/watch/#{rec['slug']}" if rec.get("slug") else None,
            "wikipedia": (rec.get("wiki") or {}).get("url") or None}


@router.get("/feed.json")
async def json_feed(response: Response, request: Request):
    """JSON Feed 1.1 of the latest stories, an hour behind the live (subscriber) stream. Each item
    names the public figures in it, with links to their JSON records."""
    _public(response, request)
    base = "https://lyraauth.com"
    items = []
    for e in live.hub.recent(100, delay=live.TEASER_DELAY):
        named = [p for p in e.get("people", [])]
        items.append({
            "id": e["id"], "url": e["url"], "title": e["title"],
            "content_text": f"{e['title']} ({e.get('source') or 'news'}). People: "
                            + (", ".join(p["name"] for p in named) or "none named")
                            + (". Companies: " + ", ".join(c["name"] for c in e.get("companies", [])) if e.get("companies") else ""),
            "date_published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e.get("published") or e["ts"])),
            "tags": e.get("topics", []) + e.get("moves", []),
            "_lyra": {"tone": e.get("tone"), "feed": e.get("feed"),
                      "people": [{"name": p["name"], "job": p.get("job"), "popularity": (p.get("popularity") or {}).get("score"),
                                  "url": f"{base}/api/watch/people/{p['id']}" if p.get("id") else None} for p in named],
                      "companies": e.get("companies", [])},
        })
    return JSONResponse(media_type="application/feed+json", headers=dict(response.headers), content={
            "version": "https://jsonfeed.org/version/1.1", "title": "Lyra Watch",
            "home_page_url": f"{base}/watch/", "feed_url": f"{base}/api/watch/feed.json",
            "description": "What the media says about politicians, investors, executives and public figures. "
                           "Stories appear here an hour after subscribers see them live.",
            "items": items})


@router.get("/feed")
async def feed(response: Response, request: Request, kind: str = "", limit: int = 80):
    _public(response, request)
    if kind not in ("", "trade", "statement"):
        raise HTTPException(400, "kind must be trade or statement")
    return {"moves": service.feed(min(max(limit, 1), 200), kind)}


# ── Live (subscribers) ─────────────────────────────────────────────────────

@router.get("/health")
async def watch_health(response: Response):
    """For monitors: 200 when everything is updating, 503 with the problems when it isn't."""
    h = service.health()
    response.status_code = 200 if h["ok"] else 503
    response.headers["Cache-Control"] = "no-store"
    return h


@router.get("/live/status")
async def live_status(response: Response, request: Request):
    """Public: whether the feed is live, how many are watching, events in the last 24 hours."""
    _public(response, request)
    response.headers["Cache-Control"] = "no-store"
    return live.hub.status()


@router.get("/live/preview")
async def live_preview(response: Response, request: Request):
    """Public taste of the feed: a few events, an hour late."""
    _public(response, request)
    return {"delay_seconds": live.TEASER_DELAY, "events": live.hub.recent(5, delay=live.TEASER_DELAY)}


@router.get("/live/recent")
async def live_recent(limit: int = 50, user: User = Depends(require_paid("watch_live"))):
    return {"events": live.hub.recent(min(max(limit, 1), live.HISTORY))}


@router.get("/live/peer")
async def live_peer(response: Response, limit: int = 100, x_lyra_peer_key: str = Header(default="")):
    """Live events for trusted nodes (e.g. the owner's trader), keyed by LYRA_PEER_KEY. 404 without it."""
    expected = os.environ.get("LYRA_PEER_KEY", "")
    if not expected or not hmac.compare_digest(x_lyra_peer_key, expected):
        raise HTTPException(404, "Not found")
    response.headers["Cache-Control"] = "no-store"
    return {"events": live.hub.recent(min(max(limit, 1), live.HISTORY))}


@router.get("/live/buzz")
async def live_buzz(user: User = Depends(require_paid("watch_live"))):
    """Who is being discussed most right now (Hacker News, Bluesky, and Reddit when configured)."""
    rows = sorted(live.loop.buzz.values(), key=lambda b: b.get("total", 0), reverse=True)
    return {"people": rows, "reddit": live.chatter.reddit_enabled()}


@router.get("/live/stream")
async def live_stream(request: Request, user: User = Depends(require_paid("watch_live"))):
    """Server-sent events: `event: item` per new headline, `event: status` with the viewer
    count every 30 s, and a comment line every 15 s so proxies keep the connection open.
    Sign in with the Authorization header (fetch + ReadableStream), not a token in the URL."""
    q = live.hub.subscribe()

    async def events():
        try:
            yield f"event: status\ndata: {json.dumps(live.hub.status())}\n\n"
            ticks = 0
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    if "_buzz" in event:
                        yield f"event: buzz\ndata: {json.dumps(event['_buzz'])}\n\n"
                    else:
                        yield f"event: item\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    ticks += 1
                    yield ": ping\n\n"
                    if ticks % 2 == 0:
                        yield f"event: status\ndata: {json.dumps(live.hub.status())}\n\n"
        finally:
            live.hub.unsubscribe(q)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
