"""Lyra Watch email alerts: big news, and any topics a reader chooses.

People opt in on /watch/account/. A background loop reads the live event log and sends each
reader what matched since their last email. Readers without Watch Pro get stories an hour
late, the same as the free feed. X posts are never emailed: X's terms keep them on the site.
"""
import asyncio
import html
import json
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from lyra import mail
from lyra.watch import trust

logger = logging.getLogger(__name__)

CHECK_SECONDS = 300
INSTANT_GAP = 900             # at least 15 minutes between emails
MAX_PER_DAY = 6               # "as it happens" readers
MAX_STORIES = 8               # per email
DAILY_HOUR_UTC = 8
CATCH_UP = 86400              # after downtime, look back no further than this
BIG_POPULARITY = 65           # 0-100, see people.popularity
QUIET_KINDS = ("wiki", "attention", "discussion")
FREE_TOPICS, PRO_TOPICS = 3, 20
TOPIC_LENGTH = 60
SEND_GAP = 0.6                # keeps a bulk run under the mail provider's rate limit


def clean_topics(raw: List[str], limit: int) -> List[str]:
    """Trimmed, de-duplicated topics, cut to the reader's limit."""
    seen, out = set(), []
    for t in raw:
        t = " ".join(str(t).split())[:TOPIC_LENGTH]
        if len(t) >= 2 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit]


def is_big(event: Dict) -> bool:
    """Big news: a real development (a move, not chatter) about someone widely followed,
    or a move announced by a government office."""
    if event.get("kind") in QUIET_KINDS or not event.get("moves"):
        return False
    if event.get("kind") == "official":
        return True
    return any(((p.get("popularity") or {}).get("score") or 0) >= BIG_POPULARITY for p in event.get("people", []))


def matched_topic(event: Dict, topics: List[str]) -> Optional[str]:
    """The first topic found in the headline, people, companies or subject tags."""
    text = " ".join([event.get("title", ""), *[p.get("name", "") for p in event.get("people", [])],
                     *[c.get("name", "") if isinstance(c, dict) else str(c) for c in event.get("companies", [])],
                     *[str(t) for t in event.get("topics", [])]])
    for topic in topics:
        if re.search(rf"(?<!\w){re.escape(topic)}(?!\w)", text, re.I):
            return topic
    return None


def select(events: List[Dict], big_news: bool, topics: List[str]) -> List[Tuple[Dict, str]]:
    """(event, why it was chosen) for one reader, newest first, one per headline, no X posts."""
    out, titles = [], set()
    for e in sorted(events, key=lambda x: x["ts"], reverse=True):
        title = re.sub(r"\W+", " ", e.get("title", "")).lower().strip()
        if e.get("x") or not title or title in titles:
            continue
        check = trust.assess(e, events)
        topic = matched_topic(e, topics)
        # Old stories never alert, and a rumour counts as big news only if it's about a chosen topic.
        if check["label"] == "old news" or not (topic or (big_news and is_big(e) and check["label"] != "rumour")):
            continue
        titles.add(title)
        why = f"Matches your topic: {topic}" if topic else "Big news"
        out.append(({**e, "trust_line": trust.describe(check)}, why))
    return out


def _safe_url(url: str) -> str:
    return url if url.startswith(("https://", "http://")) else mail.APP_URL + "/watch/"


def render(stories: List[Tuple[Dict, str]], unsub_url: str, settings_url: str) -> Tuple[str, str, str]:
    """(subject, text, html) for one email."""
    shown = stories[:MAX_STORIES]
    subject = (f"Lyra Watch: {shown[0][0]['title'][:90]}" if len(shown) == 1
               else f"Lyra Watch: {len(stories)} new stories")
    rows, lines = [], []
    for e, why in shown:
        source = e.get("source") or "News"
        rows.append(f'<div style="padding:14px 0;border-top:1px solid #eee9e1;">'
                    f'<div style="font-size:12px;color:#6e6b67;">{html.escape(why)} · {html.escape(source)}</div>'
                    f'<a href="{html.escape(_safe_url(e["url"]), quote=True)}" style="color:#14120e;font-weight:600;'
                    f'text-decoration:none;">{html.escape(e["title"])}</a>'
                    f'<div style="font-size:12px;color:#6e6b67;margin-top:3px;">{html.escape(e.get("trust_line", ""))}</div></div>')
        lines.append(f"{e['title']}\n{why} · {source}\n{e.get('trust_line', '')}\n{_safe_url(e['url'])}\n")
    more = len(stories) - len(shown)
    tail = f'<p style="margin:14px 0 0;">{more} more on the site.</p>' if more > 0 else ""
    body = "".join(rows) + tail + f'<p style="margin:20px 0 0;">{mail.button(mail.APP_URL + "/watch/", "Open Lyra Watch")}</p>'
    footer = (f'<div style="margin-bottom:8px;">You chose to get these alerts. '
              f'<a href="{html.escape(settings_url, quote=True)}" style="color:#6e6b67;">Change alerts</a> · '
              f'<a href="{html.escape(unsub_url, quote=True)}" style="color:#6e6b67;">Unsubscribe</a><br>'
              f'Not financial advice.</div>')
    text = ("\n".join(lines) + (f"\n{more} more on the site.\n" if more > 0 else "")
            + f"\nChange alerts: {settings_url}\nUnsubscribe: {unsub_url}\nNot financial advice.\n")
    return subject, text, mail.page("New on Lyra Watch", body, footer)


def is_due(frequency: str, last_sent: float, now: float) -> bool:
    if frequency == "daily":
        day = time.gmtime(now)
        return day.tm_hour >= DAILY_HOUR_UTC and time.gmtime(last_sent)[:3] != day[:3]
    return now - last_sent >= INSTANT_GAP


def load_events(since: float) -> List[Dict]:
    """Events from the saved log, which outlasts the hub's short in-memory history."""
    from lyra.watch.live import EVENTS_FILE
    from lyra.watch import xapi
    out = []
    try:
        with EVENTS_FILE.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("ts", 0) > since and not xapi.expired(e):
                    out.append(e)
    except OSError:
        pass
    return out


def run_once(db, now: Optional[float] = None, send=mail.send_email, pause: float = SEND_GAP) -> int:
    """One pass over every reader with alerts on. Returns how many emails went out."""
    from lyra.api.watch_access import has_watch
    from lyra.db.models import User, WatchAlert
    from lyra.watch.live import TEASER_DELAY
    now = now or time.time()
    alerts = db.query(WatchAlert).filter(WatchAlert.enabled == True).all()  # noqa: E712
    if not alerts:
        return 0
    events = load_events(now - CATCH_UP - TEASER_DELAY)
    sent = 0
    for a in alerts:
        user = db.get(User, a.user_id)
        if not user or not user.is_active or not is_due(a.frequency, a.last_sent or 0, now):
            continue
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        if a.sent_day != today:
            a.sent_day, a.sent_count = today, 0
        if a.frequency != "daily" and (a.sent_count or 0) >= MAX_PER_DAY:
            continue
        upto = now - (0 if has_watch(user, db) else TEASER_DELAY)
        since = max(a.cursor or 0, now - CATCH_UP - TEASER_DELAY)
        stories = select([e for e in events if since < e["ts"] <= upto], a.big_news, json.loads(a.topics or "[]"))
        if stories:
            unsub = f"{mail.APP_URL}/watch/unsubscribe/?token={a.unsub_token}"
            subject, text, body = render(stories, unsub, f"{mail.APP_URL}/watch/account/#alerts")
            one_click = f"<{mail.APP_URL}/api/watch/alerts/unsubscribe?token={a.unsub_token}>"
            if not send(user.email, subject, text, body_html=body, from_addr=_alerts_from(),
                        headers={"List-Unsubscribe": one_click, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}):
                continue          # cursor stays put, so the next pass tries again
            a.last_sent, a.sent_count = now, (a.sent_count or 0) + 1
            sent += 1
            time.sleep(pause)
        a.cursor = upto
        db.commit()
    return sent


def _alerts_from() -> str:
    import os
    return os.getenv("LYRA_ALERTS_FROM", "")


class AlertLoop:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None

    @staticmethod
    def _pass():
        from lyra.db.database import SessionLocal
        db = SessionLocal()
        try:
            return run_once(db)
        finally:
            db.close()

    async def _run(self):
        while True:
            try:
                if mail.configured():
                    await asyncio.to_thread(self._pass)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Watch alerts error: {e}")
            await asyncio.sleep(CHECK_SECONDS)

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


alert_loop = AlertLoop()
