"""Lyra Newswire API: search global news and new research with filters.

  GET /api/wire/search   q, kind (news|research), topics, country, language, tickers, people,
                         source, since, until (unix seconds), limit, offset
  GET /api/wire/facets   counts for the filter panel (same filters)
  GET /api/wire/stats    how much is stored and how every source is doing
  GET /api/wire/ticker/{ticker}   for a Tremor reading: politicians and policy news, other
                         coverage and research about the company

Visitors get a taste: the first FREE_RESULTS results and no paging. Members (a paid plan or a
trial) and Watch Pro subscribers search everything.
"""
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from lyra.api import entitlements
from lyra.db.database import get_db
from lyra.newswire.store import get_wire

router = APIRouter(prefix="/api/wire", tags=["newswire"])

FREE_RESULTS = 10
PAGE_MAX = 100
_facet_cache: Dict[str, tuple] = {}


def _full_access(request: Request, db: Session) -> bool:
    from lyra.api.page_access import is_member
    from lyra.api.watch_access import has_watch
    user = entitlements.user_from_conn(request, db)
    return bool(user and (is_member(user) or has_watch(user, db)))


def _filters(q, kind, topics, country, language, tickers, people, source, since, until) -> Dict:
    return {"q": q[:200], "kind": kind[:40], "topics": topics[:40], "country": country[:120], "language": language[:60],
            "tickers": tickers[:12], "people": people[:120], "source": source[:80], "since": since, "until": until}


@router.get("/search")
def search(request: Request, response: Response, q: str = "", kind: str = "", topics: str = "", country: str = "",
           language: str = "", tickers: str = "", people: str = "", source: str = "", since: Optional[float] = None,
           until: Optional[float] = None, limit: int = 30, offset: int = 0, db: Session = Depends(get_db)):
    f = _filters(q, kind, topics, country, language, tickers, people, source, since, until)
    full = _full_access(request, db)
    if full:
        response.headers["Cache-Control"] = "private, no-store"
        out = get_wire().search(f, limit=min(max(limit, 1), PAGE_MAX), offset=max(0, min(offset, 100000)))
        return {**out, "full": True}
    response.headers["Cache-Control"] = "public, max-age=120"
    out = get_wire().search(f, limit=FREE_RESULTS, offset=0)
    return {**out, "full": False, "locked": max(0, out["total"] - len(out["results"])),
            "unlock": "/dashboard/register.html?next=/news/"}


@router.get("/facets")
def facets(response: Response, q: str = "", kind: str = "", topics: str = "", country: str = "", language: str = "",
           tickers: str = "", people: str = "", source: str = "", since: Optional[float] = None, until: Optional[float] = None):
    f = _filters(q, kind, topics, country, language, tickers, people, source, since, until)
    key = repr(sorted(f.items()))
    hit = _facet_cache.get(key)
    if hit and time.time() - hit[0] < 300:
        data = hit[1]
    else:
        data = get_wire().facets(f)
        if len(_facet_cache) > 500:
            _facet_cache.clear()
        _facet_cache[key] = (time.time(), data)
    response.headers["Cache-Control"] = "public, max-age=300"
    return data


@router.get("/stats")
def stats(response: Response):
    response.headers["Cache-Control"] = "public, max-age=60"
    return get_wire().stats()


@router.get("/ticker/{ticker}")
def for_ticker(ticker: str, request: Request, response: Response, db: Session = Depends(get_db)):
    """What Tremor shows beside a reading: politicians and policy news naming the company,
    everything else written about it, and new research that could move it."""
    t = ticker.upper().strip()[:12]
    full = _full_access(request, db)
    n = 25 if full else 5
    since = time.time() - 30 * 86400
    w = get_wire()
    politics = w.search({"tickers": t, "topics": "politics", "since": since}, limit=n)["results"]
    policy = w.search({"tickers": t, "topics": "trade-policy", "since": since}, limit=n)["results"]
    seen = {r["id"] for r in politics}
    policy = [r for r in policy if r["id"] not in seen]
    news = w.search({"tickers": t, "kind": "news", "since": since}, limit=n)
    research = w.search({"tickers": t, "kind": "research", "since": time.time() - 90 * 86400}, limit=n)["results"]
    politicians: Dict[str, int] = {}
    counted = {}
    for r in politics + policy + news["results"]:
        counted.setdefault(r["id"], r)
    for r in counted.values():
        for p in r["people"]:
            politicians[p] = politicians.get(p, 0) + 1
    response.headers["Cache-Control"] = "private, no-store" if full else "public, max-age=300"
    return {"ticker": t, "full": full, "people_in_coverage": sorted(politicians.items(), key=lambda x: -x[1])[:15],
            "politics_and_policy": politics + policy[: max(0, n - len(politics))], "news": news["results"],
            "news_total_30d": news["total"], "research": research,
            **({} if full else {"unlock": "/dashboard/register.html?next=/market"})}
