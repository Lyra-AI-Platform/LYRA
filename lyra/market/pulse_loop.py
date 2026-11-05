"""Keeps the shared picture fresh, once a minute, for everyone at once: the leaderboard, Breaking
stories, Tremor spikes and follower alerts. Viewers only read the result, so a busy page costs
no extra work. New Tremor readings are taken for the companies most in the news, one at a time."""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Set

from lyra.market import leaderboard, live_events, pulse
from lyra.market.store import get_store
from lyra.newswire import config as C
from lyra.newswire.store import get_wire

logger = logging.getLogger(__name__)

TICK = 60
READ_EVERY = 90             # a fresh Tremor reading at most this often
READ_TOP = 20               # for the companies most in the news
READING_MAX_AGE = 2 * 3600
TRADES_EVERY = 600
NAMES = {}
for _name, _ticker in C.COMPANIES.items():
    NAMES.setdefault(_ticker, _name)


class PulseLoop:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self.board: List[Dict] = []
        self.updated = 0.0
        self.trades: Dict[str, int] = {}
        self.trades_at = 0.0
        self.announced: Set[str] = set()
        self.last_stress: Dict[str, int] = {}
        self.last_read = 0.0

    def _recent_trades(self) -> Dict[str, int]:
        """Disclosed trades in the last 30 days per company, from Watch data."""
        if time.time() - self.trades_at < TRADES_EVERY:
            return self.trades
        from datetime import datetime, timedelta, timezone
        from lyra.watch import analysis, service
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        counts: Dict[str, int] = {}
        for row in service.feed(500, "trade"):
            if str(row.get("date", "")) < cutoff:
                continue
            for c in analysis.companies_in(row.get("title", "")):
                if c["ticker"]:
                    counts[c["ticker"]] = counts.get(c["ticker"], 0) + 1
        self.trades, self.trades_at = counts, time.time()
        return counts

    def refresh_board(self) -> List[Dict]:
        stresses = get_store().stress_latest()
        self.board = leaderboard.build(get_wire().activity(), stresses, self._recent_trades(), NAMES, previous=self.board or None)
        self.updated = time.time()
        return self.board

    def _publish(self, event: Dict) -> None:
        from lyra.watch.live import hub
        hub.publish(event)

    def announce_breaking(self) -> List[Dict]:
        fresh = [c for c in get_wire().clusters({"since": time.time() - 3600}, limit=200, by_importance=True)
                 if c["breaking"] and c["id"] not in self.announced]
        for c in fresh:
            self.announced.add(c["id"])
            self._publish(live_events.breaking_event(c))
        return fresh

    def detect_spikes(self) -> List[Dict]:
        found = []
        for ticker, r in get_store().stress_latest(max_age=86400).items():
            before = self.last_stress.get(ticker)
            self.last_stress[ticker] = r["stress"]
            if pulse.is_spike(before, r["stress"]):
                stories = get_wire().clusters({"tickers": ticker, "since": time.time() - 86400}, limit=3, by_importance=True)
                event = live_events.spike_event(ticker, NAMES.get(ticker, ticker), before, r["stress"], stories)
                self._publish(event)
                found.append(event)
        return found

    async def read_next(self) -> None:
        """One fresh reading for the most-covered company without a recent one."""
        if time.time() - self.last_read < READ_EVERY:
            return
        recent = get_store().stress_latest(max_age=READING_MAX_AGE)
        activity = get_wire().activity()
        for ticker in sorted(activity, key=lambda t: -activity[t]["day"])[:READ_TOP]:
            if ticker not in recent and ticker.isalpha():
                self.last_read = time.time()
                from lyra.market import expert
                await expert.analyze(ticker, save=False, owner="pulse")
                return

    def send_alerts(self, breaking: List[Dict], spikes: List[Dict]) -> None:
        if not breaking and not spikes:
            return
        from lyra import mail
        from lyra.api import entitlements
        from lyra.db.database import SessionLocal
        from lyra.db.models import LiveFollow, User
        db = SessionLocal()
        try:
            now = time.time()
            for row in db.query(LiveFollow).filter(LiveFollow.alerts == True).all():  # noqa: E712
                f = {"kind": row.kind, "value": row.value, "alerts": row.alerts, "last_alert": row.last_alert}
                if not live_events.may_alert(f, now):
                    continue
                hit = next((e["title"] for e in spikes if live_events.spike_matches(f, e["spike"]["ticker"])), None) \
                    or next((c["title"] for c in breaking if live_events.matches(f, c)), None)
                user = db.get(User, row.user_id) if hit else None
                if user and entitlements.has_markets(user):
                    subject = f"Lyra: {hit}"[:140]
                    mail.send_email(user.email, subject, f"{hit}\n\nOpen Live: {mail.APP_URL}/watch/live/?channel=mine")
                    row.last_alert = now
            db.commit()
        finally:
            db.close()

    async def tick(self) -> None:
        self.refresh_board()
        self.send_alerts(self.announce_breaking(), self.detect_spikes())
        await self.read_next()

    async def _run(self):
        await asyncio.sleep(30)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Pulse loop error: {e}")
            await asyncio.sleep(TICK)

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


pulse_loop = PulseLoop()
