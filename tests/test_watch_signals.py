"""Wikipedia edits, attention spikes, official statements and court cases. Network calls are faked."""
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from email.utils import formatdate

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-signals-test-"))

import pytest  # noqa: E402

from lyra.watch import live, service, signals  # noqa: E402

STARMER = {"name": "Keir Starmer", "slug": "keir-starmer", "title": "Keir_Starmer"}


def _state():
    return {"revisions": {}, "spikes": {}, "official": [], "courts": []}


def _fake(routes):
    async def fetch(url, **kw):
        for key, body in routes.items():
            if key in url:
                return body if isinstance(body, str) else json.dumps(body)
        return None
    return fetch


def _revisions(revid, size, comment, minor=False):
    return {"query": {"pages": [{"title": "Keir Starmer", "revisions": [
        {"revid": revid, "parentid": revid - 1, "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "size": size, "comment": comment, **({"minor": True} if minor else {})}]}]}}


def test_edit_news_rules():
    assert signals.edit_is_news({"comment": "He resigned today", "size": 10}, 10).startswith("edit summary mentions")
    assert signals.edit_is_news({"comment": "copyedit", "size": 5000}, 1000).startswith("large edit (+4,000")
    assert signals.edit_is_news({"comment": "copyedit", "size": 1010}, 1000) is None
    assert signals.edit_is_news({"comment": "Reverted vandalism: died", "size": 10}, 10) is None
    assert signals.edit_is_news({"comment": "died", "size": 10, "minor": True}, 10) is None


def test_wiki_edits_first_sighting_is_silent_then_news_edits_count(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(signals.asyncio, "sleep", no_sleep)
    state = _state()
    monkeypatch.setattr(signals, "fetch_text", _fake({"w/api.php": _revisions(100, 290000, "wording")}))
    assert asyncio.run(signals.wiki_edits([STARMER], state)) == []
    monkeypatch.setattr(signals, "fetch_text", _fake({"w/api.php": _revisions(101, 290010, "typo")}))
    assert asyncio.run(signals.wiki_edits([STARMER], state)) == []  # small, unremarkable edit
    monkeypatch.setattr(signals, "fetch_text", _fake({"w/api.php": _revisions(102, 290050, "Appointed to the Lords")}))
    [e] = asyncio.run(signals.wiki_edits([STARMER], state))
    assert e["kind"] == "wiki" and "appointed" in e["title"].lower()
    assert e["url"] == "https://en.wikipedia.org/w/index.php?diff=102&oldid=101" and "user" not in e


def test_attention_spike_once_per_day(monkeypatch):
    days = [datetime.now(timezone.utc) - timedelta(days=i) for i in range(10, -1, -1)]
    rows = [{"timestamp": d.strftime("%Y%m%d00"), "views": 4000} for d in days[:-1]]
    rows.append({"timestamp": days[-1].strftime("%Y%m%d00"), "views": 40000})
    monkeypatch.setattr(signals, "fetch_text", _fake({"pageviews": {"items": rows}}))
    state = _state()
    spike = asyncio.run(signals.attention_spike(STARMER, state))
    assert spike["kind"] == "attention" and spike["stats"] == {"views": 40000, "usual": 4000, "ratio": 10.0}
    assert time.time() - spike["published"] < 5  # dated when detected, so it can go live
    assert asyncio.run(signals.attention_spike(STARMER, state)) is None  # already announced today
    rows[-1]["views"] = 6000
    assert asyncio.run(signals.attention_spike(STARMER, _state())) is None  # 1.5x isn't a spike


def test_official_feeds_announce_new_items_only(monkeypatch):
    feed = f"""<rss><channel><item><title>Prime Minister meets Keir Starmer</title><link>https://gov/1</link>
      <pubDate>{formatdate(time.time() - 600)}</pubDate></item></channel></rss>"""
    monkeypatch.setattr(signals, "fetch_text", _fake({"whitehouse": feed, "gov.uk": "<rss><channel></channel></rss>"}))
    state = _state()
    [item] = asyncio.run(signals.official(state))
    assert item["kind"] == "official" and item["source"] == "White House"
    assert asyncio.run(signals.official(state)) == []


def test_court_cases_require_the_person_as_a_party(monkeypatch):
    monkeypatch.setattr(signals, "fetch_text", _fake({"courtlistener": {"results": [
        {"caseName": "Musk v. OpenAI", "court": "N.D. Cal.", "dateFiled": "2026-10-10", "suitNature": "Contract",
         "docketNumber": "3:26-cv-1", "docket_absolute_url": "/docket/1/musk-v-openai/", "party": ["Elon Musk", "OpenAI"]},
        {"caseName": "Miller v. Airbnb, Inc.", "court": "S.D. Tex.", "dateFiled": "2026-10-16",
         "docket_absolute_url": "/docket/2/", "party": ["Diana Miller", "Airbnb, Inc."]}]}}))
    cases = asyncio.run(signals.court_cases({"name": "Elon Musk"}))
    assert [c["case"] for c in cases] == ["Musk v. OpenAI"]
    assert cases[0]["url"] == "https://www.courtlistener.com/docket/1/musk-v-openai/"


def test_signals_loop_publishes_fresh_signals(monkeypatch):
    monkeypatch.setattr(live, "hub", live.Hub())
    monkeypatch.setattr(live.hub, "history", live.deque(maxlen=live.HISTORY))
    monkeypatch.setattr(live.hub, "arrivals", live.deque(maxlen=50_000))
    monkeypatch.setattr(signals, "STATE_FILE", signals.WATCH_DIR / "signals-test.json")
    signals.STATE_FILE.unlink(missing_ok=True)  # the data folder outlives a test run
    monkeypatch.setattr(live, "_tracked", lambda: [STARMER])
    monkeypatch.setattr(live, "_people_lookup", lambda: {})
    monkeypatch.setattr(live, "load_roster", lambda: [{"name": "Keir Starmer", "slug": "keir-starmer", "role": "MP"}])

    async def edits(people, state):
        return [{"kind": "wiki", "platform": "Wikipedia", "person": STARMER, "title": "Wikipedia: Keir Starmer edited",
                 "url": "https://wiki/diff/1", "published": time.time() - 60, "source": "Wikipedia"}]

    async def offic(state):
        return [{"kind": "official", "platform": "10 Downing Street", "source": "10 Downing Street",
                 "title": "Old statement", "url": "https://gov/old", "published": time.time() - 3 * 86400}]

    async def no_spike(person, state):
        return None
    monkeypatch.setattr(signals, "wiki_edits", edits)
    monkeypatch.setattr(signals, "official", offic)
    monkeypatch.setattr(signals, "attention_spike", no_spike)
    asyncio.run(live.SignalsLoop().run_once())
    [e] = list(live.hub.history)
    assert e["kind"] == "wiki" and e["people"][0]["name"] == "Keir Starmer"  # the 3-day-old statement isn't live news


def test_new_court_cases_reach_the_live_feed_once(monkeypatch):
    monkeypatch.setattr(live, "hub", live.Hub())
    monkeypatch.setattr(live.hub, "history", live.deque(maxlen=live.HISTORY))
    monkeypatch.setattr(live.hub, "arrivals", live.deque(maxlen=50_000))
    monkeypatch.setattr(signals, "STATE_FILE", signals.WATCH_DIR / "signals-courts-test.json")
    signals.STATE_FILE.unlink(missing_ok=True)  # the data folder outlives a test run
    monkeypatch.setattr(live, "_people_lookup", lambda: {})
    monkeypatch.setattr(live, "load_roster", lambda: [{"name": "Elon Musk", "slug": "elon-musk", "role": "CEO"}])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cases = [{"case": "Musk v. OpenAI", "court": "N.D. Cal.", "filed": today, "nature": "Contract", "url": "https://cl/1"},
             {"case": "Old v. Case", "court": "D. Del.", "filed": "2026-01-01", "nature": "", "url": "https://cl/2"}]
    person = {"name": "Elon Musk", "slug": "elon-musk"}
    service._announce_cases(person, cases)
    service._announce_cases(person, cases)
    [e] = list(live.hub.history)
    assert e["kind"] == "court" and "Musk v. OpenAI" in e["title"]
