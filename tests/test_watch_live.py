"""Lyra Watch Live: events, fan-out and the subscriber gate. Network calls are faked."""
import asyncio
import os
import tempfile
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-live-test-"))

from lyra.api import watch_api  # noqa: E402
from lyra.api.users_api import get_current_user  # noqa: E402
from lyra.db.models import User  # noqa: E402
from lyra.watch import chatter, live, service, sources  # noqa: E402

STARMER = {"slug": "keir-starmer", "name": "Keir Starmer", "role": "Former UK Prime Minister"}


def _item(title, url, age=60):
    return {"title": f"{title} - BBC", "source": "BBC", "url": url, "summary": "", "published": time.time() - age,
            "own_words": False}


EMPTY_BUZZ = {"hours": 24, "platforms": {}, "threads": [], "total": 0, "tone": {"avg": 0, "label": "neutral"}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    async def no_discussion(person, hours=24, max_age=0):
        return dict(EMPTY_BUZZ)
    monkeypatch.setattr(live.chatter, "discussion", no_discussion)
    monkeypatch.setattr(live, "hub", live.Hub())
    monkeypatch.setattr(live.hub, "history", live.deque(maxlen=live.HISTORY))
    monkeypatch.setattr(live.hub, "arrivals", live.deque(maxlen=50_000))
    monkeypatch.setattr(live, "load_roster", lambda: [STARMER])
    service.save_people({"built_at": 1.0, "people": [
        {"name": "Andy Burnham", "slug": "", "watched": False, "job": "Prime Minister of the United Kingdom",
         "wiki": {"status": "ok"}, "popularity": {"score": 80, "tier": "Household name"}},
        {"name": "Stanislav Carpiuc", "slug": "", "watched": False, "job": "", "wiki": {"status": "none"},
         "popularity": {"score": 7, "tier": "Niche"}}]})


def test_event_names_public_figures_only():
    e = live.make_event(_item("Andy Burnham and Stanislav Carpiuc: Starmer arson case closes", "u1"), STARMER,
                        live._people_lookup())
    names = [p["name"] for p in e["people"]]
    assert names == ["Keir Starmer", "Andy Burnham"]  # the private individual isn't named
    assert e["people"][1]["popularity"]["score"] == 80 and e["title"].endswith("closes")
    assert e["feed_slug"] == "keir-starmer"


def test_hub_fans_out_and_keeps_history():
    a, b = live.hub.subscribe(), live.hub.subscribe()
    assert live.hub.status()["viewers"] == 2
    live.hub.publish({"id": "x", "ts": time.time(), "title": "t"})
    assert a.get_nowait()["id"] == "x" and b.get_nowait()["id"] == "x"
    live.hub.unsubscribe(a)
    assert live.hub.status()["viewers"] == 1 and live.hub.status()["events_today"] == 1
    assert live.hub.recent(delay=3600) == []  # the public preview runs an hour behind


def test_loop_announces_only_new_recent_headlines(monkeypatch):
    feed = [_item("Keir Starmer speaks", "u1"), _item("Old Starmer story", "u2", age=86400)]

    async def fake_statements(person, max_age=0):
        return list(feed), {"status": "ok"}
    monkeypatch.setattr(sources, "statements", fake_statements)
    loop = live.LiveLoop()
    loop.seen = set()
    asyncio.run(loop.check(STARMER, {}, announce=False))  # the first pass only learns what's already out
    assert len(live.hub.history) == 0 and loop.seen == {"u1", "u2"}
    feed.append(_item("Andy Burnham meets Keir Starmer", "u3"))
    assert asyncio.run(loop.check(STARMER, live._people_lookup())) == 1
    assert [e["id"] for e in live.hub.history] == ["u3"]
    assert asyncio.run(loop.check(STARMER, {})) == 0  # nothing repeats


def _client(tier):
    app = FastAPI()
    app.include_router(watch_api.router)
    if tier:
        app.dependency_overrides[get_current_user] = lambda: User(id=1, email="a@b.c", tier=tier)
    return TestClient(app)


def test_status_and_preview_are_public():
    live.hub.publish({"id": "old", "ts": time.time() - 7200, "title": "old"})
    live.hub.publish({"id": "new", "ts": time.time(), "title": "new"})
    c = _client(None)
    assert c.get("/api/watch/live/status").json()["events_today"] == 2
    assert [e["id"] for e in c.get("/api/watch/live/preview").json()["events"]] == ["old"]


def test_subscribers_only():
    assert _client(None).get("/api/watch/live/recent").status_code == 401
    r = _client("free").get("/api/watch/live/recent")
    assert r.status_code == 402 and r.json()["detail"]["reason"] == "subscribers_only"
    assert _client("free").get("/api/watch/live/stream").status_code == 402
    live.hub.publish({"id": "n", "ts": time.time(), "title": "n"})
    assert [e["id"] for e in _client("starter").get("/api/watch/live/recent").json()["events"]] == ["n"]


def test_stream_sends_status_then_items(monkeypatch):
    class FakeRequest:
        calls = 0

        async def is_disconnected(self):
            FakeRequest.calls += 1
            return FakeRequest.calls > 1

    async def run():
        resp = await watch_api.live_stream(FakeRequest(), user=User(id=1, tier="pro"))
        it = resp.body_iterator
        first = await it.__anext__()
        live.hub.publish({"id": "s1", "ts": time.time(), "title": "Breaking"})
        second = await it.__anext__()
        await it.aclose()
        return first, second
    first, second = asyncio.run(run())
    assert first.startswith("event: status") and '"viewers": 1' in first
    assert second.startswith("event: item") and '"s1"' in second
    assert live.hub.status()["viewers"] == 0  # leaving unsubscribes


def test_live_loop_survives_errors(monkeypatch):
    calls = {"n": 0}

    async def flaky_tickers():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("SEC is down")
        raise asyncio.CancelledError  # stop the test after the retry

    async def no_sleep(_):
        return None
    monkeypatch.setattr(sources, "known_tickers", flaky_tickers)
    monkeypatch.setattr(live.asyncio, "sleep", no_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(live.LiveLoop()._run())
    assert calls["n"] == 2  # it retried instead of dying


def test_health_reports_stale_data(monkeypatch):
    from lyra.api import watch_api as api
    monkeypatch.setattr(service.refresh_loop, "alive", lambda: True)
    monkeypatch.setattr(live.loop, "alive", lambda: True)
    monkeypatch.setattr(live.loop, "last_check", time.time() - 60)
    service.save_people({"built_at": time.time() - 600, "people": []})
    assert service.health()["ok"]
    service.save_people({"built_at": time.time() - 3 * 86400, "people": []})
    monkeypatch.setattr(live.loop, "last_check", time.time() - 7200)
    h = service.health()
    assert not h["ok"] and "people index is stale" in h["problems"] and len(h["problems"]) == 2
    app = FastAPI()
    app.include_router(api.router)
    assert TestClient(app).get("/api/watch/health").status_code == 503


def test_daily_count_is_not_capped_by_history():
    for i in range(live.HISTORY + 50):
        live.hub.publish({"id": str(i), "ts": time.time(), "title": "t"})
    assert len(live.hub.history) == live.HISTORY
    assert live.hub.status()["events_today"] == live.HISTORY + 50


def test_dates_in_every_feed_format_are_read():
    from datetime import datetime, timezone
    from lyra.market import news
    want = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc).timestamp()
    assert news._parse_date("2026-07-18T10:00:00+00:00") == want      # YouTube / Atom
    assert news._parse_date("2026-07-18T10:00:00Z") == want
    assert news._parse_date("Sat, 18 Jul 2026 10:00:00 +0000") == want  # RSS
    assert news._parse_date("18 Jul 2026 10:00 +0000") == want          # Bluesky
    assert news._parse_date("next Tuesday") == 0.0                      # unknown is old, never "now"


def test_an_old_youtube_video_is_not_live_news(monkeypatch):
    three_months_ago = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 90 * 86400))
    just_now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 120))
    feed = f"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Old town hall</title><link href="https://youtube.com/watch?v=old"/><published>{three_months_ago}</published></entry>
      <entry><title>New statement</title><link href="https://youtube.com/watch?v=new"/><published>{just_now}</published></entry>
    </feed>"""

    async def fake_fetch(url, **kw):
        return feed if "youtube" in url else "<rss><channel></channel></rss>"
    monkeypatch.setattr(sources, "fetch_text", fake_fetch)
    monkeypatch.setattr(chatter, "fetch_text", fake_fetch)
    monkeypatch.setattr(service, "load_profile", lambda slug: {"own_feeds": [
        {"platform": "YouTube", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC1"}]})
    loop = live.LiveLoop()
    loop.seen = {"something-else"}  # not the first pass
    asyncio.run(loop.check(STARMER, {}))
    assert [e["id"] for e in live.hub.history] == ["https://youtube.com/watch?v=new"]
    e = live.hub.history[0]
    assert e["kind"] == "post" and e["platform"] == "YouTube" and time.time() - e["published"] < 300


def test_events_saved_before_the_date_fix_are_dropped(monkeypatch):
    import json as _json
    monkeypatch.setattr(live, "EVENTS_FILE", live.WATCH_DIR / "events-test.jsonl")
    live.EVENTS_FILE.write_text(_json.dumps({"id": "old", "ts": time.time(), "title": "t"}) + "\n" +
                                _json.dumps({"v": live.EVENT_VERSION, "id": "ok", "ts": time.time(), "title": "t"}) + "\n")
    hub = live.Hub()
    assert [e["id"] for e in hub.history] == ["ok"] and len(hub.arrivals) == 1


def test_trending_threads_become_events_and_buzz_is_sent(monkeypatch):
    now = time.time()

    async def buzzing(person, hours=24, max_age=0):
        return {**EMPTY_BUZZ, "total": 42, "platforms": {"Hacker News": {"mentions": 42, "avg": 0, "label": "neutral"}},
                "threads": [{"platform": "Hacker News", "title": "Starmer's AI plan, explained", "url": "https://hn/1",
                             "score": 80, "comments": 40, "published": now - 600},
                            {"platform": "Hacker News", "title": "Quiet thread", "url": "https://hn/2",
                             "score": 2, "comments": 1, "published": now - 600}]}
    monkeypatch.setattr(live.chatter, "discussion", buzzing)
    q = live.hub.subscribe()
    loop = live.LiveLoop()
    asyncio.run(loop.discuss(STARMER, {}))
    assert [e["id"] for e in live.hub.history] == ["https://hn/1"]  # the quiet thread isn't news
    e = live.hub.history[0]
    assert e["kind"] == "discussion" and e["stats"] == {"score": 80, "comments": 40}
    msgs = [q.get_nowait() for _ in range(q.qsize())]
    assert msgs[0]["_buzz"]["total"] == 42 and msgs[0]["_buzz"]["slug"] == "keir-starmer"
    asyncio.run(loop.discuss(STARMER, {}))
    assert len(live.hub.history) == 1  # announced once
