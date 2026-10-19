"""Builds and stores one profile per watched person, and a combined feed of
everyone's latest moves. Profiles are rebuilt in the background, so page
visits never trigger fetches against the SEC, the House Clerk or news sites."""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from lyra.watch import analysis, chatter, impact, people, signals, sources, xapi
from lyra.watch.config import CATEGORIES, LOOKBACK_DAYS, PROFILES_DIR, REFRESH_HOURS, WATCH_DIR, load_roster

logger = logging.getLogger(__name__)

PUBLIC_FIELDS = ("slug", "name", "category", "country", "role")
PEOPLE_FILE = WATCH_DIR / "people.json"


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


def _media(items: List[Dict], person: Dict) -> List[Dict]:
    """Annotated headlines in the compact form the people index is built from."""
    out = []
    for it in items:
        title = people.headline(it)
        # Google News summaries are just the title and the outlet again; only real summaries are read.
        summary = "" if it.get("summary", "").startswith(title[:40]) else it.get("summary", "")
        out.append({"title": title, "summary": summary, "url": it["url"], "source": it.get("source", ""),
                    "date": time.strftime("%Y-%m-%d", time.gmtime(it["published"])), "sentiment": it["sentiment"],
                    "companies": it["companies"], "topics": it.get("topics", []),
                    "moves": [m["kind"] for m in it.get("moves", [])],
                    "own_words": bool(it.get("own_words")), "platform": it.get("platform", ""),
                    "interview": bool(it.get("interview")),
                    "reported": bool(it.get("reported")), "people": people.names_in(f"{title}. {summary}" if summary else title),
                    "feed": person["name"]})
    return out


async def accounts_for(person: Dict) -> Dict:
    """Wikipedia match, Wikidata facts and the person's own readable feeds, found once per refresh."""
    try:
        wiki = await sources.wiki_person(person)
    except Exception:  # noqa: BLE001
        wiki = {"status": "unavailable"}
    wd = await sources.wikidata_profile(wiki.get("qid", "")) if wiki.get("status") == "ok" else {}
    accounts = wd.get("accounts", {})
    try:
        feeds = await sources.own_feeds(person, accounts)
    except Exception:  # noqa: BLE001
        feeds = []
    links = sources.account_links(accounts)
    read = {f["platform"].lower() for f in feeds}
    for link in links:
        # ✓ only when a feed for that platform actually loaded (a website may have none),
        # or for X when the X API is connected.
        link["read"] = (link["read"] and link["platform"] in read) or (link["platform"] == "x" and xapi.enabled())
    return {"wiki": wiki, "wikidata": wd, "accounts": links, "own_feeds": feeds}


async def build_profile(person: Dict, tickers=frozenset()) -> Dict:
    found = await accounts_for(person)
    wiki = found["wiki"]
    tasks = {"statements": sources.statements({**person, "feeds": found["own_feeds"]}),
             "discussion": chatter.discussion(person), "courts": signals.court_cases(person)}
    if person.get("sec_cik"):
        tasks["insider"] = sources.form4_trades(person["sec_cik"])
    if person.get("fund_cik"):
        tasks["fund"] = sources.fund_moves(person["fund_cik"])
    if person.get("house"):
        tasks["congress"] = sources.house_trades(person["house"]["last"], person["house"]["state"])
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    data, status = {}, {}
    buzz = results[1] if isinstance(results[1], dict) else {}
    cases = results[2] if isinstance(results[2], list) else []
    for key, r in zip(tasks, results):
        if key in ("discussion", "courts"):
            continue
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
        "media": _media(items, person),
        "wiki": wiki,
        "accounts": found["accounts"],
        "own_feeds": found["own_feeds"],
        "posts": [{**{k: it.get(k) for k in ("url", "source", "platform", "published", "sentiment", "reported")},
                   "title": people.headline(it)} for it in items if it.get("own_words") or it.get("reported")][:30],
        "interviews": [{**{k: it.get(k) for k in ("url", "source", "platform", "published")}, "title": people.headline(it)}
                       for it in items if it.get("interview")][:20],
        "discussion": buzz,
        "court_cases": cases,
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


def card(person: Dict, index: Optional[Dict] = None) -> Dict:
    """The roster entry plus headline numbers from its stored profile."""
    p = load_profile(person["slug"]) or {}
    s = p.get("summary", {})
    rated = next((r for r in (index if index is not None else load_people()).get("people", [])
                  if r.get("slug") == person["slug"]), {})
    return {**{k: person.get(k, "") for k in PUBLIC_FIELDS},
            "category_label": CATEGORIES.get(person.get("category", ""), "Other"),
            "stance": _stance(person), "built_at": p.get("built_at"),
            "trades": len(p.get("trades", [])), "moves": len(p.get("moves", [])),
            "top_companies": [c["name"] for c in s.get("companies", [])[:3]],
            "top_topics": [t["topic"] for t in s.get("topics", [])[:3]],
            "latest": (p.get("moves") or [{}])[0].get("title", ""),
            "popularity": rated.get("popularity"), "media_mentions": rated.get("mentions", 0)}


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


def _announce_cases(person: Dict, cases: List[Dict]):
    """New court cases filed in the last two days go to the live feed once."""
    from lyra.watch import live
    state = signals._load_state()
    fresh = False
    for c in cases:
        if c["url"] in state["courts"]:
            continue
        state["courts"].append(c["url"])
        fresh = True
        try:
            filed = datetime.strptime(c["filed"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if time.time() - filed < 2 * 86400:
            live.hub.publish(live.signal_event(
                {"kind": "court", "platform": "US federal court", "person": person, "source": c["court"],
                 "title": f"New case: {c['case']} ({c['court']}{', ' + c['nature'] if c['nature'] else ''})",
                 "url": c["url"], "published": filed + 43200}, live._people_lookup()))
    if fresh:
        signals._save_state(state)


def load_people() -> Dict:
    try:
        return json.loads(PEOPLE_FILE.read_text())
    except (OSError, ValueError):
        return {}


async def build_people(roster: List[Dict]) -> Dict:
    """Everyone the coverage names, rated for popularity. Watched people reuse the Wikipedia
    lookup from their profile; everyone else is looked up here (cached for days)."""
    profiles = {p["slug"]: load_profile(p["slug"]) or {} for p in roster}
    index = people.build_index([m for pr in profiles.values() for m in pr.get("media", [])], roster)
    gate = asyncio.Semaphore(4)

    async def wiki(rec):
        if rec["watched"]:
            return profiles[rec["slug"]].get("wiki") or {"status": "unavailable"}
        async with gate:
            try:
                return await sources.wiki_person({"name": rec["name"]})
            except Exception:  # noqa: BLE001
                return {"status": "unavailable"}
    records = list(index.values())
    views = {}
    for rec, w in zip(records, await asyncio.gather(*(wiki(r) for r in records))):
        rec["wiki"] = {k: w.get(k) for k in ("status", "title", "description", "url", "qid")}
        views[rec["name"]] = w.get("daily_views")
    # Spellings that lead to the same article are one person ("Zelensky", "Zelenskyy").
    groups: Dict[str, List[Dict]] = {}
    for rec in records:
        key = rec["wiki"]["title"] if rec["wiki"]["status"] == "ok" else people.fold(rec["name"])
        groups.setdefault(key, []).append(rec)
    records = [people.merge(g) for g in groups.values()]
    for rec in records:
        w = rec["wiki"]
        rec["popularity"] = people.popularity(views.get(rec["name"]), rec["mentions"], w.get("status") or "unavailable")
        # Wikipedia's one-line description beats a phrase lifted from a headline.
        if not rec["watched"] and w.get("description"):
            rec["job"], rec["job_source"] = w["description"], "wikipedia"
    # A name built from two rare words, with no known first name, needs backing: a Wikipedia
    # article about a person, or a headline that gives them a job title.
    records = [r for r in records if r["watched"] or r["known_first_name"] or r["wiki"]["status"] == "ok"
               or r["job_source"] == "headline"]
    facts = await asyncio.gather(*(_wikidata(r, gate) for r in records))
    for rec, wd in zip(records, facts):
        rec["politics"] = politics(rec, wd, next((p for p in roster if p["slug"] == rec["slug"]), None))
        rec["occupations"] = wd.get("occupations", [])
        # Off the watchlist nothing is read, so these are links only.
        rec["accounts"] = [{**a, "read": False} for a in sources.account_links(wd.get("accounts", {}))]
        if rec["watched"]:
            prof = profiles.get(rec["slug"], {})
            rec["accounts"] = prof.get("accounts", rec["accounts"])
            rec["own_feeds"] = prof.get("own_feeds", [])
            rec["posts"] = prof.get("posts", [])[:10]
            rec["interviews"] = prof.get("interviews", [])[:10]
            rec["discussion"] = prof.get("discussion", {})
            rec["court_cases"] = prof.get("court_cases", [])
            rec["trades"] = prof.get("trades", [])
    try:
        await impact.measure(records)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Market impact failed: {e}")
    for rec in records:
        rec.pop("trades", None)  # the full list stays on the profile
        rec.pop("ticker_days", None)  # kept in the impact history instead
    records.sort(key=lambda r: (r["popularity"]["score"], r["mentions"]), reverse=True)
    return {"built_at": time.time(), "people": records}


async def _wikidata(rec: Dict, gate: asyncio.Semaphore) -> Dict:
    if (rec.get("wiki") or {}).get("status") != "ok":
        return {}
    async with gate:
        try:
            return await sources.wikidata_profile(rec["wiki"].get("qid", ""))
        except Exception:  # noqa: BLE001
            return {}


# Wikidata "positions held" also lists corporate roles; only public office counts here.
_POLITICAL_OFFICE = re.compile(
    r"president|prime minister|minister|chancellor|member of|senator|representative|governor|mayor|"
    r"secretary|speaker|parliament|congress|senate|assembly|council|lok sabha|bundestag|crown prince|"
    r"monarch|king of|queen of|ambassador|judge|justice|leader of|party|vice president|press secretary|"
    r"\bMP\b|\bMEP\b", re.I)


def politics(rec: Dict, wd: Dict, person: Optional[Dict]) -> Dict:
    """A political profile built only from documented facts: the sourced roster affiliation or
    Wikidata's party membership and current offices, plus how much of their coverage is political.
    Lyra never infers where someone stands from their words."""
    stance = _stance(person) if person else {"basis": "none"}
    if stance["basis"] == "documented":
        parties, source = [stance["label"]], stance["source"]
    else:
        parties, source = wd.get("parties", []), wd.get("source", "")
    offices = [o for o in wd.get("offices", []) if _POLITICAL_OFFICE.search(o)]
    return {"parties": parties, "offices": offices,
            "basis": "documented" if parties or offices else "none",
            "source": (source or wd.get("source", "")) if parties or offices else "",
            "political_coverage": rec.get("political_coverage", 0.0)}


def save_people(data: Dict):
    tmp = PEOPLE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(PEOPLE_FILE)


def is_public_figure(rec: Dict) -> bool:
    """Shown publicly: the watchlist, plus people with a Wikipedia article about them. Private
    individuals who turn up in a headline (a witness, a defendant) stay in the local index only."""
    return rec.get("watched") or (rec.get("wiki") or {}).get("status") == "ok"


def person_record(pid: str) -> Optional[Dict]:
    """One public person by id (or a former spelling's id)."""
    for r in load_people().get("people", []):
        if is_public_figure(r) and (r.get("id") == pid or pid in {people.person_id(n) for n in r.get("also_known_as", [])}):
            return r
    return None


def people_list(q: str = "", watched: Optional[bool] = None, limit: int = 100, public: bool = True,
                ticker: str = "") -> Dict:
    """`ticker` keeps the people whose coverage names that company (used by the market page)."""
    data = load_people()
    q = q.lower().strip()
    ticker = ticker.upper().strip()
    rows = [r for r in data.get("people", [])
            if (not public or is_public_figure(r)) and (not q or q in f"{r['name']} {r['job']} {r.get('described_as', '')} {' '.join(c['name'] for c in r['companies'])}".lower())
            and (watched is None or r["watched"] == watched)
            and (not ticker or any((c.get("ticker") or "").upper() == ticker for c in r["companies"]))]
    return {"built_at": data.get("built_at"), "total": len(rows), "people": rows[:limit]}


async def refresh_all():
    tickers = await sources.known_tickers()
    roster = load_roster()
    for person in roster:
        try:
            profile = await build_profile(person, tickers)
            save_profile(profile)
            _announce_cases(person, profile.get("court_cases", []))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Watch profile {person['slug']} failed: {e}")
        await asyncio.sleep(1)  # stay polite to the SEC and the House Clerk
    try:
        save_people(await build_people(roster))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Watch people index failed: {e}")


class RefreshLoop:
    """Background task: rebuild every profile every few hours."""

    def __init__(self, interval_hours: float = REFRESH_HOURS):
        self.interval = interval_hours * 3600
        self._task: Optional[asyncio.Task] = None
        self.last_run: Optional[float] = None

    async def _run(self):
        while True:
            try:
                await refresh_all()
                self.last_run = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Watch refresh error: {e}")
            await asyncio.sleep(self.interval)

    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        if not self.alive():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


refresh_loop = RefreshLoop()


def health() -> Dict:
    """Is everything still updating? `ok` is false when a loop has stopped or the data is stale:
    the people index older than two refresh intervals, or no live check for 30 minutes."""
    from lyra.watch import live
    now = time.time()
    built = load_people().get("built_at")
    people_age = now - built if built else None
    live_age = now - live.loop.last_check if live.loop.last_check else None
    problems = []
    if not refresh_loop.alive():
        problems.append("refresh loop stopped")
    if not live.loop.alive():
        problems.append("live loop stopped")
    if people_age is None or people_age > 2 * refresh_loop.interval + 3600:
        problems.append("people index is stale")
    if live_age is not None and live_age > 1800:
        problems.append("live feed hasn't checked a source in 30 minutes")
    if not live.signals_loop.alive():
        problems.append("signals loop stopped")
    return {"ok": not problems, "problems": problems,
            "people_index_age_minutes": round(people_age / 60) if people_age is not None else None,
            "last_live_check_minutes": round(live_age / 60, 1) if live_age is not None else None,
            "refresh_every_hours": refresh_loop.interval / 3600, "live_cycle_minutes": live.LIVE_CYCLE_MINUTES,
            "last_signals_check_minutes": round((now - live.signals_loop.last_run) / 60, 1) if live.signals_loop.last_run else None,
            "sources": {"x": xapi.status(), "gdelt": chatter.gdelt_status(), "reddit": "on" if chatter.reddit_enabled() else "off (no API credentials)"}}
