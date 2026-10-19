"""Fast signals about public figures, from sources that need no account:

- Wikipedia edits: the latest revision of each tracked person's article, checked every few
  minutes. A large edit, or one whose summary says something happened (died, resigned,
  arrested...), is often the first sign of news.
- Attention spikes: a person's Wikipedia readership jumping far above its usual level.
- Official statements: White House and 10 Downing Street news feeds.
- Court cases: new US federal cases (CourtListener / RECAP) where the person is a named party.

Editors' usernames are never kept; an edit is shown by its summary and a link to the diff.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from statistics import median
from typing import Dict, List, Optional
from urllib.parse import quote, quote_plus

from lyra.market import news
from lyra.market.config import SEC_USER_AGENT
from lyra.market.fetch import fetch_text
from lyra.watch.config import WATCH_DIR

logger = logging.getLogger(__name__)
UA = {"User-Agent": SEC_USER_AGENT}

REVISIONS = ("https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles={titles}"
             "&rvprop=ids|timestamp|comment|size|flags&format=json&formatversion=2")
DIFF = "https://en.wikipedia.org/w/index.php?diff={revid}&oldid={parentid}"
DAILY_VIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
               "{title}/daily/{start}/{end}")
COURTS = ("https://www.courtlistener.com/api/rest/v4/search/?type=r&order_by=dateFiled%20desc"
          "&party_name={name}&filed_after={after}")

OFFICIAL_FEEDS = {
    "White House": "https://www.whitehouse.gov/news/feed/",
    "10 Downing Street": ("https://www.gov.uk/search/news-and-communications.atom?"
                          "organisations%5B%5D=prime-ministers-office-10-downing-street"),
}

# Edit summaries that suggest something happened to the person.
NEWSWORTHY_EDIT = re.compile(
    r"\b(died|death|dies|passed away|resign\w*|elected|appointed|nominat\w*|arrest\w*|charged|indict\w*|"
    r"convicted|sentenced|married|divorc\w*|engaged|hospital\w*|sworn in|steps? down|fired|ousted|acquir\w*|"
    r"impeach\w*|assassinat\w*|killed|injured|announc\w*|launch\w*)\b", re.I)
BIG_EDIT_BYTES = 1500
SPIKE_RATIO = 3.0       # today's readers vs the usual day
SPIKE_MIN_VIEWS = 5000


# ── Wikipedia edits ────────────────────────────────────────────────────────

STATE_FILE = WATCH_DIR / "signals_state.json"


def _load_state() -> Dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"revisions": {}, "spikes": {}, "official": [], "courts": []}


def _save_state(state: Dict):
    try:
        state["official"] = state.get("official", [])[-2000:]
        state["courts"] = state.get("courts", [])[-5000:]
        STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass


def edit_is_news(rev: Dict, size_before: Optional[int]) -> Optional[str]:
    """Why an edit matters ("large edit", "summary mentions 'resigned'"), or None."""
    comment = rev.get("comment", "") or ""
    if rev.get("minor") or re.search(r"\bbot\b|reverted|undid|rv\b|vandal", comment, re.I):
        return None
    m = NEWSWORTHY_EDIT.search(comment)
    if m:
        return f"edit summary mentions “{m.group(0)}”"
    if size_before is not None and abs(rev.get("size", 0) - size_before) >= BIG_EDIT_BYTES:
        return f"large edit ({rev.get('size', 0) - size_before:+,} bytes)"
    return None


async def wiki_edits(people: List[Dict], state: Dict) -> List[Dict]:
    """New revisions of the people's articles since the last check, as event dicts.
    `people`: [{"name", "title", ...}]. The first sighting of an article only records it."""
    events = []
    by_title = {p["title"]: p for p in people if p.get("title")}
    titles = list(by_title)
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        body = await fetch_text(REVISIONS.format(titles="|".join(quote(t) for t in chunk)), max_age=0, headers=UA)
        try:
            pages = json.loads(body)["query"]["pages"] if body else []
        except (ValueError, KeyError):
            continue
        for page in pages:
            revs = page.get("revisions") or []
            if not revs:
                continue
            rev, title = revs[0], page["title"].replace(" ", "_")
            person = by_title.get(title) or by_title.get(page["title"])
            known = state["revisions"].get(title)
            state["revisions"][title] = {"revid": rev["revid"], "size": rev.get("size")}
            if not person or not known or known["revid"] == rev["revid"]:
                continue
            why = edit_is_news(rev, known.get("size"))
            if not why:
                continue
            events.append({"kind": "wiki", "platform": "Wikipedia", "person": person,
                           "title": f"Wikipedia: {page['title']} edited — {why}"
                                    + (f": “{rev['comment'][:120]}”" if rev.get("comment") else ""),
                           "url": DIFF.format(revid=rev["revid"], parentid=rev.get("parentid", 0)),
                           "published": _iso(rev.get("timestamp", "")), "source": "Wikipedia"})
        await asyncio.sleep(1)
    return events


def _iso(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


# ── Attention spikes ───────────────────────────────────────────────────────

async def attention_spike(person: Dict, state: Dict) -> Optional[Dict]:
    """An event when the latest day's readers are SPIKE_RATIO times the person's usual day.
    Announced once per person per day."""
    title = person.get("title")
    if not title:
        return None
    end = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(end.timestamp() - 30 * 86400, timezone.utc)
    body = await fetch_text(DAILY_VIEWS.format(title=quote_plus(title, safe="_%"), start=start.strftime("%Y%m%d"),
                                               end=end.strftime("%Y%m%d")), max_age=3 * 3600, headers=UA)
    try:
        rows = json.loads(body)["items"] if body else []
    except (ValueError, KeyError):
        return None
    if len(rows) < 8:
        return None
    latest, usual = rows[-1], median(r["views"] for r in rows[:-1])
    day = latest["timestamp"][:8]
    if latest["views"] < SPIKE_MIN_VIEWS or latest["views"] < SPIKE_RATIO * max(usual, 1):
        return None
    if state["spikes"].get(title) == day:
        return None
    state["spikes"][title] = day
    ratio = latest["views"] / max(usual, 1)
    return {"kind": "attention", "platform": "Wikipedia", "person": person, "source": "Wikipedia readership",
            "title": f"Attention spike: {person['name']} — {latest['views']:,} Wikipedia readers on "
                     f"{day[:4]}-{day[4:6]}-{day[6:]}, {ratio:.1f}× a usual day",
            "url": f"https://pageviews.wmcloud.org/?pages={quote(title)}&project=en.wikipedia.org&range=latest-30",
            # Readership figures arrive a day or more late; the spike is news when they do, so it's
            # dated now. The day it describes is in the title.
            "published": time.time(), "day": f"{day[:4]}-{day[4:6]}-{day[6:]}",
            "stats": {"views": latest["views"], "usual": round(usual), "ratio": round(ratio, 1)}}


# ── Official statements ────────────────────────────────────────────────────

async def official(state: Dict) -> List[Dict]:
    """New items from government news feeds. People are attached later by name."""
    out = []
    for office, url in OFFICIAL_FEEDS.items():
        body = await fetch_text(url, max_age=240, headers=UA)
        for it in news.parse_feed(body or ""):
            if it["url"] in state["official"]:
                continue
            state["official"].append(it["url"])
            out.append({"kind": "official", "platform": office, "source": office, "title": it["title"],
                        "url": it["url"], "published": it["published"], "summary": it.get("summary", "")})
    return out


# ── Court cases ────────────────────────────────────────────────────────────

async def court_cases(person: Dict, days: int = 30) -> List[Dict]:
    """US federal cases filed in the last `days` with the person as a named party."""
    name = re.sub(r"\s*\(.*?\)", "", person["name"]).strip()
    after = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).strftime("%m/%d/%Y")
    body = await fetch_text(COURTS.format(name=quote(f'"{name}"'), after=quote(after, safe="")), max_age=6 * 3600,
                            headers=UA)
    try:
        rows = json.loads(body).get("results", []) if body else []
    except ValueError:
        return []
    surname = name.split()[-1].lower()
    cases = []
    for r in rows:
        parties = " ".join(r.get("party") or []).lower()
        if name.lower() not in parties and surname not in (r.get("caseName") or "").lower():
            continue  # the name only appears inside documents, not as a party
        cases.append({"case": r.get("caseName", ""), "court": r.get("court", ""), "filed": r.get("dateFiled", ""),
                      "nature": r.get("suitNature", ""), "docket": r.get("docketNumber", ""),
                      "url": "https://www.courtlistener.com" + (r.get("docket_absolute_url") or "")})
    return cases[:15]
