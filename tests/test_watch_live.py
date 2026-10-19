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
from lyra.watch import live, service, sources  # noqa: E402

STARMER = {"slug": "keir-starmer", "name": "Keir Starmer", "role": "Former UK Prime Minister"}


def _item(title, url, age=60):
    return {"title": f"{title} - BBC", "source": "BBC", "url": url, "summary": "", "published": time.time() - age,
            "own_words": False}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
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
