"""
COSHH AI API
Public substance safety lookups: a compiled 16-section SDS with UK WELs and
COSHH guidance, plus NIST spectra. Rate limited per IP. Nothing a visitor
uploads (their own lab spectra, supplier SDS PDFs) is sent here: those stay
in the visitor's browser.
"""
import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response

from lyra.coshh import sds, sources, wel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/coshh", tags=["coshh"])

LIMITS = {"sheet": int(os.environ.get("LYRA_COSHH_SHEETS_PER_HOUR", 120)),
          "light": int(os.environ.get("LYRA_COSHH_LIGHT_PER_HOUR", 1200))}
SHEET_MAX_AGE = 7 * 86400
_hits: Dict[str, Deque[float]] = defaultdict(deque)


def _limit(kind: str, request: Request):
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    now = time.time()
    q = _hits[f"{kind}:{ip}"]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= LIMITS[kind]:
        raise HTTPException(429, f"Rate limit reached ({LIMITS[kind]} per hour). Try again later.",
                            headers={"Retry-After": str(int(3600 - (now - q[0])) + 1)})
    q.append(now)


def _upstream_error(e: Exception):
    logger.warning(f"COSHH upstream error: {e}")
    raise HTTPException(502, "The data source (PubChem / NIST) didn't answer. Try again in a minute.")


@router.get("/search")
async def search(request: Request, response: Response, q: str = Query(..., min_length=2, max_length=100)):
    """Name suggestions as the user types."""
    _limit("light", request)
    try:
        names = await sources.autocomplete(q)
    except httpx.HTTPError as e:
        _upstream_error(e)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {"query": q, "suggestions": names}


@router.get("/sheet")
async def sheet(request: Request, response: Response, q: str = Query(..., min_length=1, max_length=120),
                refresh: bool = False):
    """The compiled safety data sheet for a name, CAS number or PubChem CID."""
    _limit("sheet", request)
    try:
        cid = await sources.resolve(q)
    except sources.NotFound:
        raise HTTPException(404, f"No substance found for “{q}”. Try the CAS number or another name.")
    except httpx.HTTPError as e:
        _upstream_error(e)
    key = f"sheet:v4:{cid}"
    cached = None if refresh else sources.cache().get(key, SHEET_MAX_AGE)
    if cached:
        body = json.loads(cached)
    else:
        try:
            props = await sources.properties(cid)
            parts, failed = await sources.record_parts(cid)
        except sources.NotFound:
            raise HTTPException(404, f"PubChem has no record for CID {cid}.")
        except httpx.HTTPError as e:
            _upstream_error(e)
        body = sds.compile_sheet(cid, props, parts, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        body["incomplete"] = failed
        if not failed:  # a partial sheet is shown but not cached, so the next visit tries again
            sources.cache().put(key, json.dumps(body))
    response.headers["Cache-Control"] = "public, max-age=3600"
    return body


@router.get("/spectrum")
async def spectrum(request: Request, cas: str, kind: str = Query("IR", pattern="^(IR|Mass)$"),
                   index: int = Query(0, ge=0, lt=20)):
    """A NIST WebBook JCAMP-DX spectrum (IR or mass), passed through as text."""
    _limit("light", request)
    try:
        text = await sources.nist_jcamp(cas, kind, index)
    except ValueError:
        raise HTTPException(400, "Give a CAS number like 67-64-1.")
    except httpx.HTTPError as e:
        _upstream_error(e)
    if not text:
        raise HTTPException(404, "NIST has no spectrum of that kind for this substance.")
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=604800",
                             "X-Source": "NIST Chemistry WebBook, NIST Standard Reference Database 69"})


@router.get("/wel")
async def wel_lookup(request: Request, cas: str = "", name: str = ""):
    """The EH40 workplace exposure limit by CAS number or name."""
    _limit("light", request)
    hit = wel.lookup(cas or None, [name] if name else [])
    if not hit:
        raise HTTPException(404, "Not in EH40 Table 1. That does not mean it is safe (EH40 para 6).")
    return hit


@router.get("/wel/all")
async def wel_all(response: Response):
    """The whole EH40 Table 1, for browsing and offline use."""
    response.headers["Cache-Control"] = "public, max-age=86400"
    t = wel.table()
    return {"source": t["source"], "note": t["note"], "entries": t["entries"], "bmgv": t.get("bmgv", [])}
