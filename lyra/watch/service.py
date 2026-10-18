"""Builds and stores one profile per watched person, and a combined feed of
everyone's latest moves. Profiles are rebuilt in the background, so page
visits never trigger fetches against the SEC, the House Clerk or news sites."""
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

from lyra.watch import analysis, sources
from lyra.watch.config import CATEGORIES, LOOKBACK_DAYS, PROFILES_DIR, REFRESH_HOURS, load_roster

logger = logging.getLogger(__name__)

PUBLIC_FIELDS = ("slug", "name", "category", "country", "role")


def _stance(person: Dict) -> Dict:
    """Only a documented, sourced affiliation is shown. Political views are never inferred."""
    aff = person.get("affiliation")
    if aff and aff.get("label") and aff.get("source"):
        return {"label": aff["label"], "source": aff["source"], "basis": "documented"}
    return {"label": "Not publicly declared", "source": "", "basis": "none"}


def _trade_moves(trades: List[Dict]) -> List[Dict]:
    out = []
    for t in trades:
        if t["kind"] == "fund":
            what = {"new": "opened a position in", "add": "added to", "trim": "trimmed",
                    "exit": "exited"}[t["action"]]
            title = f"Fund {what} {t['company']}"
        elif t.get("side") == "filed":
            title = "Filed a periodic transaction report"
        else:
            verb = {"buy": "Bought", "sell": "Sold", "exchange": "Exchanged"}.get(t.get("side"), "Traded")
            amount = t.get("amount_range") or (f"${t['value']:,.0f}" if t.get("value") else "")
            opt = " (options)" if t.get("options") else ""
            title = f"{verb} {t.get('company') or t.get('ticker')}{opt}" + (f" — {amount}" if amount else "")
        out.append({"type": "trade", "kind": t["kind"], "title": title, "date": t.get("date", ""),
                    "url": t.get("url", ""), "ticker": t.get("ticker", ""), "detail": t})
    return out


async def build_profile(person: Dict, tickers=frozenset()) -> Dict:
    tasks = {"statements": sources.statements(person)}
    if person.get("sec_cik"):
        tasks["insider"] = sources.form4_trades(person["sec_cik"])
    if person.get("fund_cik"):
        tasks["fund"] = sources.fund_moves(person["fund_cik"])
    if person.get("house"):
        tasks["congress"] = sources.house_trades(person["house"]["last"], person["house"]["state"])
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    data, status = {}, {}
    for key, r in zip(tasks, results):
        if isinstance(r, Exception):
            logger.warning(f"Watch {person['slug']} {key} failed: {r}")
            data[key], status[key] = [], {"status": "failed", "detail": "lookup error"}
        else:
            data[key], status[key] = r

    items = [analysis.annotate(it, tickers) for it in data.pop("statements")]
    trades = [t for k in ("insider", "fund", "congress") for t in data.get(k, [])]
    trades.sort(key=lambda t: t.get("date", ""), reverse=True)
    power = [{"type": "statement", "title": it["title"], "date": time.strftime("%Y-%m-%d", time.gmtime(it["published"])),
              "url": it["url"], "source": it["source"], "moves": it["moves"], "companies": it["companies"]}
             for it in items if it["moves"]]
    moves = sorted(_trade_moves(trades) + power, key=lambda m: m["date"], reverse=True)
    return {
        **{k: person.get(k, "") for k in PUBLIC_FIELDS},
        "category_label": CATEGORIES.get(person.get("category", ""), "Other"),
        "stance": _stance(person),
        "built_at": time.time(),
        "lookback_days": LOOKBACK_DAYS,
        "summary": analysis.summarize(items, [t for t in trades if t.get("side") != "filed"]),
        "trades": trades[:60],
        "moves": moves[:60],
        "statements": items[:40],
        "sources": status,
    }


def _path(slug: str):
    return PROFILES_DIR / f"{slug}.json"


def load_profile(slug: str) -> Optional[Dict]:
    try:
        return json.loads(_path(slug).read_text())
    except (OSError, ValueError):
        return None


def save_profile(profile: Dict):
    tmp = _path(profile["slug"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(profile))
    tmp.replace(_path(profile["slug"]))


def card(person: Dict) -> Dict:
    """The roster entry plus headline numbers from its stored profile."""
    p = load_profile(person["slug"]) or {}
    s = p.get("summary", {})
    return {**{k: person.get(k, "") for k in PUBLIC_FIELDS},
            "category_label": CATEGORIES.get(person.get("category", ""), "Other"),
            "stance": _stance(person), "built_at": p.get("built_at"),
            "trades": len(p.get("trades", [])), "moves": len(p.get("moves", [])),
            "top_companies": [c["name"] for c in s.get("companies", [])[:3]],
            "top_topics": [t["topic"] for t in s.get("topics", [])[:3]],
            "latest": (p.get("moves") or [{}])[0].get("title", "")}


def feed(limit: int = 80, kind: str = "") -> List[Dict]:
    rows = []
    for person in load_roster():
        p = load_profile(person["slug"])
        for m in (p or {}).get("moves", []):
            if kind and m["type"] != kind:
                continue
            rows.append({**{k: m[k] for k in ("type", "title", "date", "url") if k in m},
                         "kind": m.get("kind", ""), "labels": [x["label"] for x in m.get("moves", [])],
                         "person": person["name"], "slug": person["slug"]})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit]


async def refresh_all():
    tickers = await sources.known_tickers()
    for person in load_roster():
        try:
            save_profile(await build_profile(person, tickers))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Watch profile {person['slug']} failed: {e}")
        await asyncio.sleep(1)  # stay polite to the SEC and the House Clerk


class RefreshLoop:
    """Background task: rebuild every profile every few hours."""

    def __init__(self, interval_hours: float = REFRESH_HOURS):
        self.interval = interval_hours * 3600
        self._task: Optional[asyncio.Task] = None

    async def _run(self):
        while True:
            try:
                await refresh_all()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Watch refresh error: {e}")
            await asyncio.sleep(self.interval)

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


refresh_loop = RefreshLoop()
