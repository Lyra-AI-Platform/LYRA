"""X connector: off without a token; budget, rate limits, retention and no redistribution."""
import asyncio
import os
import tempfile
import time

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-x-test-"))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.watch import live, xapi  # noqa: E402

NOW_ISO = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 120))


class FakeX:
    """Answers like the X API; records calls."""

    def __init__(self, posts=None, status=200, headers=None):
        self.posts, self.status, self.headers, self.calls = posts or [], status, headers or {}, []

    def client(self, **kw):
        fake = self

        class Resp:
            def __init__(self, status, data, headers):
                self.status_code, self._data, self.headers, self.text = status, data, headers, ""

            def json(self):
                return self._data

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None, headers=None):
                fake.calls.append((url, dict(params or {})))
                assert headers["Authorization"] == "Bearer test-token"
                if url.endswith("/users/by"):
                    return Resp(200, {"data": [{"id": "44196397", "username": "elonmusk"}]}, {})
                return Resp(fake.status, {"data": fake.posts} if fake.posts else {}, fake.headers)
        return Client()


@pytest.fixture(autouse=True)
def x_on(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(xapi, "STATE_FILE", xapi.WATCH_DIR / "x-test.json")
    xapi.STATE_FILE.unlink(missing_ok=True)


def test_off_without_a_token(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN")
    assert not xapi.enabled() and xapi.status() == {"on": False, "detail": "off (no X_BEARER_TOKEN)"}
    assert asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"])) == []


def test_first_check_records_then_new_posts_arrive(monkeypatch):
    fake = FakeX(posts=[{"id": "100", "text": "Old post", "created_at": NOW_ISO}])
    monkeypatch.setattr(xapi.httpx, "AsyncClient", fake.client)
    assert asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"])) == []  # first sighting
    fake.posts = [{"id": "101", "text": "Starship   launches   tomorrow", "created_at": NOW_ISO,
                   "public_metrics": {"like_count": 5}}]
    n = len(fake.calls)
    assert asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"])) == [] and len(fake.calls) == n  # too soon
    monkeypatch.setattr(xapi, "CHECK_MINUTES", 0)
    [item] = asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"]))
    assert item["url"] == "https://x.com/elonmusk/status/101" and item["title"] == "Starship launches tomorrow"
    assert item["x"] and item["own_words"] and item["platform"] == "X"
    url, params = fake.calls[-1]
    assert url.endswith("/users/44196397/tweets") and params["since_id"] == "100"
    assert params["exclude"] == "replies,retweets"
    assert xapi.status()["posts_read_this_month"] == 2


def test_rate_limit_pauses_and_cap_stops(monkeypatch):
    fake = FakeX(status=429, headers={"x-rate-limit-reset": str(time.time() + 600)})
    monkeypatch.setattr(xapi.httpx, "AsyncClient", fake.client)
    asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"]))
    assert xapi.status()["paused"] and xapi.status()["last_error"] == "rate limited"
    n = len(fake.calls)
    asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"]))
    assert len(fake.calls) == n  # no calls while paused

    xapi.STATE_FILE.unlink()
    monkeypatch.setattr(xapi, "MONTHLY_CAP", 0)
    fake2 = FakeX()
    monkeypatch.setattr(xapi.httpx, "AsyncClient", fake2.client)
    asyncio.run(xapi.new_posts({"name": "Elon Musk"}, ["elonmusk"]))
    assert fake2.calls == [] and xapi.status()["last_error"] == "monthly post cap reached"


def test_x_content_expires_and_stays_off_public_feeds(monkeypatch):
    from lyra.api import watch_api
    monkeypatch.setattr(live, "hub", live.Hub())
    monkeypatch.setattr(live.hub, "history", live.deque(maxlen=live.HISTORY))
    monkeypatch.setattr(live.hub, "arrivals", live.deque(maxlen=50_000))
    two_hours = time.time() - 7200
    live.hub.publish({"v": 2, "id": "https://x.com/a/status/1", "url": "https://x.com/a/status/1", "ts": two_hours,
                      "title": "an X post", "x": True, "people": [], "companies": [], "topics": [], "moves": []})
    live.hub.publish({"v": 2, "id": "https://bbc/1", "url": "https://bbc/1", "ts": two_hours, "title": "news",
                      "people": [], "companies": [], "topics": [], "moves": []})
    app = FastAPI()
    app.include_router(watch_api.router)
    c = TestClient(app)
    assert [i["id"] for i in c.get("/api/watch/feed.json").json()["items"]] == ["https://bbc/1"]
    assert [e["id"] for e in c.get("/api/watch/live/preview").json()["events"]] == ["https://bbc/1"]
    assert len(live.hub.recent(10)) == 2  # subscribers on the site still see it
    monkeypatch.setattr(xapi, "RETENTION_HOURS", 1)
    assert [e["id"] for e in live.hub.recent(10)] == ["https://bbc/1"]
    live.hub.purge_expired()
    assert [e["id"] for e in live.hub.history] == ["https://bbc/1"]
