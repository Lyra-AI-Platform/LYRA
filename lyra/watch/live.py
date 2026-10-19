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

from lyra.watch import analysis, people, service, sources
from lyra.watch.config import WATCH_DIR, load_roster

logger = logging.getLogger(__name__)

LIVE_CYCLE_MINUTES = float(os.environ.get("LYRA_WATCH_LIVE_CYCLE_MINUTES", 10))
HISTORY = 300                      # events kept for viewers who join late
TEASER_DELAY = 3600                # non-subscribers see events an hour late
EVENTS_FILE = WATCH_DIR / "live_events.jsonl"
SEEN_FILE = WATCH_DIR / "live_seen.json"


class Hub:
    """Fan-out of live events to connected viewers."""

    def __init__(self):
        self.viewers: Set[asyncio.Queue] = set()
        self.history: Deque[Dict] = deque(maxlen=HISTORY)
        self.started = time.time()
        self._load()

    def _load(self):
        try:
            for line in EVENTS_FILE.read_text().splitlines()[-HISTORY:]:
                self.history.append(json.loads(line))
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
        try:
            with EVENTS_FILE.open("a") as f:
                f.write(json.dumps(event) + "\n")
            if EVENTS_FILE.stat().st_size > 2_000_000:  # keep the file to the recent history
                EVENTS_FILE.write_text("".join(json.dumps(e) + "\n" for e in self.history))
        except OSError as e:
            logger.warning(f"Live event not saved: {e}")
        for q in list(self.viewers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # a viewer that stopped reading misses events rather than stalling everyone

    def recent(self, limit: int = 50, delay: float = 0) -> List[Dict]:
        cutoff = time.time() - delay
        return [e for e in self.history if e["ts"] <= cutoff][-limit:][::-1]

    def status(self) -> Dict:
        day = time.time() - 86400
        return {"live": loop.running, "viewers": len(self.viewers),
                "events_today": sum(e["ts"] >= day for e in self.history),
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


def make_event(item: Dict, person: Dict, lookup: Dict[str, Dict], tickers=frozenset()) -> Dict:
    """One headline as a live event. Only public figures are named (see service.is_public_figure)."""
    a = analysis.annotate(item, tickers)
    title = people.headline(item)
    names = list(dict.fromkeys([person["name"], *people.names_in(title)]))
    watched = {p["name"]: p for p in load_roster()}
    cast = []
    for n in names:
        rec = lookup.get(n) or {}
        if not rec and n not in watched:
            continue
        cast.append({"name": n, "slug": rec.get("slug") or watched.get(n, {}).get("slug", ""),
                     "job": rec.get("job") or watched.get(n, {}).get("role", ""),
                     "popularity": rec.get("popularity")})
    return {"id": item["url"], "ts": time.time(), "published": item.get("published"),
            "feed": person["name"], "feed_slug": person["slug"], "title": title, "url": item["url"],
            "source": item.get("source", ""), "people": cast, "companies": a["companies"],
            "moves": [m["label"] for m in a["moves"]], "topics": a["topics"],
            "tone": "positive" if a["sentiment"] >= 0.15 else "negative" if a["sentiment"] <= -0.15 else "neutral"}


class LiveLoop:
    """Checks one feed at a time, round-robin, and publishes headlines it hasn't seen."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self.running = False
        self.seen: Set[str] = set()
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
        items, _ = await sources.statements(person, max_age=60)
        new = [it for it in items if it["url"] not in self.seen]
        for it in sorted(new, key=lambda x: x["published"]):
            self.seen.add(it["url"])
            # Headlines from before the first check are history, not news.
            if announce and time.time() - it["published"] < 6 * 3600:
                hub.publish(make_event(it, person, lookup, tickers))
        return len(new)

    async def _run(self):
        self.running = True
        tickers = await sources.known_tickers()
        first_pass = not self.seen
        while True:
            roster = load_roster()
            pause = LIVE_CYCLE_MINUTES * 60 / max(len(roster), 1)
            lookup = _people_lookup()
            for person in roster:
                try:
                    await self.check(person, lookup, tickers, announce=not first_pass)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Live check {person['slug']} failed: {e}")
                await asyncio.sleep(pause)
            first_pass = False
            self._save_seen()

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()


loop = LiveLoop()
