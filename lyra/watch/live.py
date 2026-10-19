"""Lyra Watch Live: new headlines about the watchlist, pushed to subscribers as they land.

A background loop walks the roster one feed at a time (so each feed is checked about
every LIVE_CYCLE_MINUTES), and every headline it hasn't seen before becomes an event
naming the people in it, with their job, popularity, the companies mentioned and the
tone. Events go to every connected viewer and into a short history that survives a
restart. Nothing here is fetched per viewer: viewers only read the stream."""
import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Set

from lyra.watch import analysis, chatter, people, service, signals, sources
from lyra.watch.config import WATCH_DIR, load_roster

logger = logging.getLogger(__name__)

LIVE_CYCLE_MINUTES = float(os.environ.get("LYRA_WATCH_LIVE_CYCLE_MINUTES", 10))
HISTORY = 300                      # events kept for viewers who join late
FRESH_HOURS = 6                    # older headlines and posts are history, not live news
DISCUSSION_THRESHOLD = 30          # a thread is news once points + 2 x comments reaches this
EVENT_VERSION = 2                  # v1 events could carry a wrong published date
TEASER_DELAY = 3600                # non-subscribers see events an hour late
EVENTS_FILE = WATCH_DIR / "live_events.jsonl"
SEEN_FILE = WATCH_DIR / "live_seen.json"


class Hub:
    """Fan-out of live events to connected viewers."""

    def __init__(self):
        self.viewers: Set[asyncio.Queue] = set()
        self.history: Deque[Dict] = deque(maxlen=HISTORY)
        # Arrival times kept apart from the (shorter) history, so the 24-hour count isn't capped by it.
        self.arrivals: Deque[float] = deque(maxlen=50_000)
        self.started = time.time()
        self._load()

    def _load(self):
        try:
            for line in EVENTS_FILE.read_text().splitlines():
                event = json.loads(line)
                if event.get("v", 1) < EVENT_VERSION:
                    continue  # recorded before dates were read correctly; their ages can't be trusted
                self.history.append(event)
                self.arrivals.append(event["ts"])
        except (OSError, ValueError):
            pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.viewers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self.viewers.discard(q)

    def publish(self, event: Dict):
        self.history.append(event)
        self.arrivals.append(event["ts"])
        try:
            with EVENTS_FILE.open("a") as f:
                f.write(json.dumps(event) + "\n")
            if EVENTS_FILE.stat().st_size > 20_000_000:  # trim to the last two days
                keep = [line for line in EVENTS_FILE.read_text().splitlines()
                        if json.loads(line)["ts"] > time.time() - 2 * 86400]
                EVENTS_FILE.write_text("".join(line + "\n" for line in keep))
        except OSError as e:
            logger.warning(f"Live event not saved: {e}")
        for q in list(self.viewers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # a viewer that stopped reading misses events rather than stalling everyone

    def publish_buzz(self, buzz: Dict):
        """Discussion levels go to viewers as their own message type; they aren't stories."""
        for q in list(self.viewers):
            try:
                q.put_nowait({"_buzz": buzz})
            except asyncio.QueueFull:
                pass

    def recent(self, limit: int = 50, delay: float = 0) -> List[Dict]:
        cutoff = time.time() - delay
        return [e for e in self.history if e["ts"] <= cutoff][-limit:][::-1]

    def status(self) -> Dict:
        day = time.time() - 86400
        return {"live": loop.running and loop.alive(), "viewers": len(self.viewers),
                "events_today": sum(t >= day for t in self.arrivals),
                "last_event": self.history[-1]["ts"] if self.history else None,
                "cycle_minutes": LIVE_CYCLE_MINUTES}


hub = Hub()


def _people_lookup() -> Dict[str, Dict]:
    """Name (and alias) -> public person record from the stored people index."""
    out = {}
    for r in service.load_people().get("people", []):
        if service.is_public_figure(r):
            for n in [r["name"], *r.get("also_known_as", [])]:
                out[n] = r
    return out


def _cast(names: List[str], lookup: Dict[str, Dict]) -> List[Dict]:
    """The named people who are public figures, with job and popularity."""
    watched = {p["name"]: p for p in load_roster()}
    cast = []
    for n in names:
        rec = lookup.get(n) or {}
        if not rec and n not in watched:
            continue
        cast.append({"name": n, "slug": rec.get("slug") or watched.get(n, {}).get("slug", ""),
                     "id": rec.get("id") or watched.get(n, {}).get("slug", ""),
                     "job": rec.get("job") or watched.get(n, {}).get("role", ""),
                     "popularity": rec.get("popularity")})
    return cast


def make_event(item: Dict, person: Dict, lookup: Dict[str, Dict], tickers=frozenset()) -> Dict:
    """One headline as a live event. Only public figures are named (see service.is_public_figure)."""
    a = analysis.annotate(item, tickers)
    title = people.headline(item)
    cast = _cast(list(dict.fromkeys([person["name"], *people.names_in(title)])), lookup)
    return {"v": EVENT_VERSION, "id": item["url"], "ts": time.time(), "published": item.get("published"),
            "feed": person["name"], "feed_slug": person["slug"], "title": title, "url": item["url"],
            "source": item.get("source", ""), "people": cast, "companies": a["companies"],
            "moves": [m["label"] for m in a["moves"]], "topics": a["topics"],
            "kind": ("post" if item.get("own_words") else "reported_post" if item.get("reported")
                     else "interview" if item.get("interview") else "news"),
            "platform": item.get("platform", ""),
            "tone": "positive" if a["sentiment"] >= 0.15 else "negative" if a["sentiment"] <= -0.15 else "neutral"}


class LiveLoop:
    """Checks one feed at a time, round-robin, and publishes headlines it hasn't seen."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self.running = False
        self.last_check: Optional[float] = None
        self.seen: Set[str] = set()
        self.buzz: Dict[str, Dict] = {}   # slug -> latest discussion levels
        try:
            self.seen = set(json.loads(SEEN_FILE.read_text()))
        except (OSError, ValueError):
            pass

    def _save_seen(self):
        try:
            SEEN_FILE.write_text(json.dumps(list(self.seen)[-20000:]))
        except OSError:
            pass

    async def check(self, person: Dict, lookup: Dict[str, Dict], tickers=frozenset(), announce: bool = True) -> int:
        profile = service.load_profile(person["slug"]) or {}
        items, _ = await sources.statements({**person, "feeds": profile.get("own_feeds", [])}, max_age=60)
        new = [it for it in items if it["url"] not in self.seen]
        for it in sorted(new, key=lambda x: x["published"]):
            self.seen.add(it["url"])
            # Headlines from before the first check are history, not news.
            if announce and 0 < time.time() - it["published"] < FRESH_HOURS * 3600:
                hub.publish(make_event(it, person, lookup, tickers))
        try:
            await self.discuss(person, lookup, announce)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Live discussion {person['slug']} failed: {e}")
        return len(new)

    async def discuss(self, person: Dict, lookup: Dict[str, Dict], announce: bool = True):
        """Refresh how much the person is being discussed, and announce threads that take off."""
        d = await chatter.discussion(person, hours=24, max_age=300)
        prev = self.buzz.get(person["slug"], {})
        self.buzz[person["slug"]] = {"name": person["name"], "slug": person["slug"], **d,
                                     "change": d["total"] - prev.get("total", d["total"])}
        hub.publish_buzz(self.buzz[person["slug"]])
        for t in d["threads"]:
            if t["url"] in self.seen or t["score"] + 2 * t["comments"] < DISCUSSION_THRESHOLD:
                continue
            self.seen.add(t["url"])
            if announce and 0 < time.time() - t["published"] < FRESH_HOURS * 3600:
                hub.publish({"v": EVENT_VERSION, "id": t["url"], "ts": time.time(), "published": t["published"],
                             "feed": person["name"], "feed_slug": person["slug"], "title": t["title"], "url": t["url"],
                             "source": t.get("subreddit") or t["platform"], "people": _cast([person["name"]], lookup),
                             "companies": analysis.companies_in(t["title"]), "moves": [], "topics": [],
                             "kind": "discussion", "platform": t["platform"],
                             "stats": {"score": t["score"], "comments": t["comments"]},
                             "tone": "neutral"})

    async def _cycle(self, tickers, announce: bool):
        roster = load_roster()
        pause = LIVE_CYCLE_MINUTES * 60 / max(len(roster), 1)
        lookup = _people_lookup()
        for person in roster:
            try:
                await self.check(person, lookup, tickers, announce=announce)
                self.last_check = time.time()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Live check {person['slug']} failed: {e}")
            await asyncio.sleep(pause)
        self._save_seen()

    async def _run(self):
        """Runs until the service stops. Any failure is logged and the loop carries on a minute
        later, so a bad feed or a network outage can't end the live feed."""
        self.running = True
        first_pass = not self.seen
        while True:
            try:
                tickers = await sources.known_tickers()
                await self._cycle(tickers, announce=not first_pass)
                first_pass = False
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Live loop error, retrying in a minute: {e}")
                await asyncio.sleep(60)

    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        if not self.alive():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()


loop = LiveLoop()


def signal_event(sig: Dict, lookup: Dict[str, Dict]) -> Dict:
    """A signals.py result (Wikipedia edit, attention spike, official statement, court case) as a live event."""
    person = sig.get("person")
    names = [person["name"]] if person else []
    names += [n for n in people.names_in(sig["title"]) if n not in names]
    feed = person["name"] if person else sig.get("source", "")
    return {"v": EVENT_VERSION, "id": sig["url"], "ts": time.time(), "published": sig.get("published") or time.time(),
            "feed": feed, "feed_slug": (person or {}).get("slug", ""), "title": sig["title"], "url": sig["url"],
            "source": sig.get("source", ""), "people": _cast(names, lookup),
            "companies": analysis.companies_in(sig["title"]), "moves": [m["label"] for m in analysis.move_kinds(sig["title"])],
            "topics": analysis.topics_in(sig["title"]), "kind": sig["kind"], "platform": sig.get("platform", ""),
            "stats": sig.get("stats"), "tone": "neutral"}


def _tracked() -> List[Dict]:
    """Public figures with a Wikipedia article: [{"name", "slug", "title"}]."""
    out = []
    for r in service.load_people().get("people", []):
        title = (r.get("wiki") or {}).get("title")
        if service.is_public_figure(r) and title:
            out.append({"name": r["name"], "slug": r.get("slug", ""), "title": title})
    return out


class SignalsLoop:
    """Every few minutes: Wikipedia edits to tracked people's articles and new official statements.
    Hourly: attention spikes. Failures are logged and the loop carries on."""

    def __init__(self, every_seconds: float = 180):
        self.every = every_seconds
        self._task: Optional[asyncio.Task] = None
        self.last_run: Optional[float] = None
        self._last_spikes = 0.0

    async def run_once(self, announce: bool = True):
        state = signals._load_state()
        tracked, lookup = _tracked(), _people_lookup()
        found = await signals.wiki_edits(tracked, state)
        found += await signals.official(state)
        if time.time() - self._last_spikes > 3600:
            self._last_spikes = time.time()
            for person in tracked:
                spike = await signals.attention_spike(person, state)
                if spike:
                    found.append(spike)
                await asyncio.sleep(0.2)
        signals._save_state(state)
        for sig in sorted(found, key=lambda x: x.get("published") or 0):
            age = time.time() - (sig.get("published") or 0)
            if announce and 0 < age < FRESH_HOURS * 3600 and sig["url"] not in loop.seen:
                loop.seen.add(sig["url"])
                hub.publish(signal_event(sig, lookup))
        self.last_run = time.time()

    async def _run(self):
        first = not signals.STATE_FILE.exists()
        while True:
            try:
                await self.run_once(announce=not first)
                first = False
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Signals loop error: {e}")
            await asyncio.sleep(self.every)

    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        if not self.alive():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


signals_loop = SignalsLoop()
