"""What ties the products together: Tremor on Newswire, Newswire on Tremor.

  GET /api/pulse/card?q=          a search that names a company or sector: its Tremor card
  GET /api/pulse/sectors          stress dot for each topic chip
  GET /api/pulse/companies?tickers=A,B   mini gauge and story count per company
  GET /api/pulse/drivers/{ticker} "News driving this", with each Tremor signal's articles
  GET /api/pulse/timeline/{ticker}  "Why is it moving?" (Markets Pro)

All of it reads stored data, so a page full of cards costs no outside requests. Stress levels are
public; the full reading stays behind its daily allowance.
"""
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Response

from lyra.api import entitlements
from lyra.db.models import User
from lyra.market import pulse
from lyra.market.store import get_store
from lyra.newswire.store import get_wire

router = APIRouter(prefix="/api/pulse", tags=["pulse"])

WEEK = 7 * 86400
_cache: Dict[str, tuple] = {}


def _reading_url(ticker: str) -> str:
    return f"/tremor/reading?ticker={ticker}"


def stresses() -> Dict[str, Dict]:
    hit = _cache.get("stress")
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    data = get_store().stress_latest()
    _cache["stress"] = (time.time(), data)
    return data


async def _vix() -> Optional[Dict]:
    hit = _cache.get("vix")
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    from lyra.market.market_data import get_vix
    try:
        v = {k: x for k, x in (await get_vix()).items() if k != "history"}
    except Exception:  # noqa: BLE001 — the card just leaves the VIX out
        return None
    _cache["vix"] = (time.time(), v)
    return v


def mini(ticker: str) -> Dict:
    s = stresses().get(ticker)
    return {"ticker": ticker, "stress": s["stress"] if s else None, "level": pulse.level(s["stress"] if s else None),
            "stories_week": get_wire().stories_since(ticker, time.time() - WEEK), "reading_url": _reading_url(ticker)}


@router.get("/card")
async def card(response: Response, q: str = ""):
    response.headers["Cache-Control"] = "public, max-age=60"
    found = pulse.resolve(q)
    if not found:
        return {"match": None}
    vix = await _vix()
    if found["kind"] == "company":
        t = found["ticker"]
        reading = stresses().get(t)
        return {"match": "company", "ticker": t, "name": found["name"], **mini(t),
                "summary": pulse.plain_english(found["name"], reading, vix),
                "insiders": _flow(reading, "insider_flow"), "politicians": _flow(reading, "congress_flow"),
                "vix": vix.get("level") if vix and vix.get("available") else None}
    sector = pulse.sector_stress(found["topic"], stresses())
    return {"match": "sector", **sector, "summary": _sector_text(sector, vix),
            "companies": [mini(t) for t in found["tickers"]],
            "vix": vix.get("level") if vix and vix.get("available") else None}


def _flow(reading: Optional[Dict], key: str) -> str:
    value = ((reading or {}).get("features") or {}).get(key)
    if value is None or abs(value) < 0.1:
        return "quiet"
    return "buying" if value > 0 else "selling"


def _sector_text(sector: Dict, vix: Optional[Dict]) -> str:
    if sector["stress"] is None:
        return f"{sector['name']} has no recent Tremor readings yet."
    text = f"{sector['name']} stress is {sector['level']} at {sector['stress']}, across {sector['companies_read']} companies."
    return text + (f" The VIX is {vix['level']:.1f}." if vix and vix.get("available") else "")


@router.get("/people")
def people_cards(response: Response, names: str = ""):
    """Watch cards for the tracked people named in a set of stories: who they are, recent trades."""
    from lyra.watch import pages, service
    response.headers["Cache-Control"] = "public, max-age=300"
    out = []
    for name in dict.fromkeys(n.strip() for n in names.split("|") if n.strip()):
        rec = service.person_record(pid_for(name)) if len(out) < 25 else None
        if rec:
            profile = service.load_profile(rec["slug"]) if rec.get("slug") else None
            out.append({"name": rec["name"], "job": rec.get("job", ""), "page": f"/watch/{rec['id']}", "trades": pages.trades_of(profile)})
    return {"people": out}


def pid_for(name: str) -> str:
    from lyra.watch.people import person_id
    return person_id(name)


@router.get("/sectors")
def sectors(response: Response):
    response.headers["Cache-Control"] = "public, max-age=120"
    return {"sectors": [pulse.sector_stress(t, stresses()) for t in pulse.SECTORS]}


@router.get("/companies")
def companies(response: Response, tickers: str = ""):
    response.headers["Cache-Control"] = "public, max-age=120"
    wanted = [t.strip().upper()[:12] for t in tickers.split(",") if t.strip()][:30]
    return {"companies": [mini(t) for t in dict.fromkeys(wanted)]}


@router.get("/drivers/{ticker}")
def drivers(ticker: str, response: Response):
    """The latest stories on a company, and which of them stand behind each Tremor signal."""
    t = ticker.upper().strip()[:12]
    response.headers["Cache-Control"] = "public, max-age=120"
    rows = get_wire().clusters({"tickers": t, "since": time.time() - WEEK}, limit=60)
    reading = stresses().get(t)
    signals = []
    if reading:
        from lyra.market.tremor_index import EXPLAIN
        for factor, value in reading["features"].items():
            words = EXPLAIN.get(factor)
            text = (words[0] if value > 0 else words[1]) if words and abs(value) >= 0.1 else ""
            if text:
                signals.append({"factor": factor, "value": value, "reason": text})
    return {"ticker": t, "stories": rows[:8], "signals": [s for s in pulse.link_signals(signals, rows) if s["articles"]]}


@router.get("/timeline/{ticker}")
def timeline(ticker: str, response: Response, days: int = 30,
             _: User = Depends(entitlements.require_markets("timeline"))):
    t = ticker.upper().strip()[:12]
    now, since = time.time(), time.time() - min(max(days, 7), 90) * 86400
    response.headers["Cache-Control"] = "private, no-store"
    w = get_wire()
    return {"ticker": t, **pulse.timeline(w.hourly(t, since), get_store().stress_rows(t, since), w.spikes(t, since), since, now)}
