"""
Lyra Watch API — public figures' disclosed trades, power moves and statements.

Read-only and public: everything comes from public records and is rebuilt in the
background, so requests only read stored profiles. Rate limited per IP.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import APIRouter, HTTPException, Request, Response

from lyra.watch import service
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


@router.get("/feed")
async def feed(response: Response, request: Request, kind: str = "", limit: int = 80):
    _public(response, request)
    if kind not in ("", "trade", "statement"):
        raise HTTPException(400, "kind must be trade or statement")
    return {"moves": service.feed(min(max(limit, 1), 200), kind)}
