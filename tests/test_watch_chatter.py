"""GDELT, podcasts, Hacker News, Bluesky and (optional) Reddit. Network calls are faked."""
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from email.utils import formatdate

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-chatter-test-"))

from lyra.watch import chatter, sources  # noqa: E402

NOW = time.time()
STAMP = datetime.fromtimestamp(NOW - 1800, timezone.utc)
STARMER = {"name": "Keir Starmer"}


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def open_gate(monkeypatch):
    monkeypatch.setattr(chatter, "GDELT_INTERVAL", 0.0)
    monkeypatch.setitem(chatter._gdelt_state, "next", 0.0)
    monkeypatch.setitem(chatter._gdelt_state, "refusals", 0)


def _fake(routes):
    async def fetch(url, **kw):
        for key, body in routes.items():
            if key in url:
                return body if isinstance(body, str) else json.dumps(body)
        return None
    return fetch


def test_gdelt_articles_become_items(monkeypatch):
    monkeypatch.setattr(chatter, "fetch_text", _fake({"gdeltproject": {"articles": [
        {"url": "https://a/1", "title": "Starmer speaks", "domain": "bbc.co.uk", "seendate": STAMP.strftime("%Y%m%dT%H%M%SZ")}]}}))
    [it] = asyncio.run(chatter.gdelt(STARMER))
    assert it["source"] == "bbc.co.uk" and abs(it["published"] - (NOW - 1800)) < 2 and it["via"] == "GDELT"
    monkeypatch.setattr(chatter, "fetch_text", _fake({"gdeltproject": "Please limit requests to one every 5 seconds"}))
    assert asyncio.run(chatter.gdelt(STARMER)) == []
    monkeypatch.setitem(chatter._gdelt_state, "next", 0.0)


def test_podcasts_need_the_name_and_a_recent_date(monkeypatch):
    recent, old = STAMP.strftime("%Y-%m-%dT%H:%M:%SZ"), "2025-01-01T00:00:00Z"
    monkeypatch.setattr(chatter, "fetch_text", _fake({"itunes": {"results": [
        {"trackName": "Keir Starmer on what comes next", "collectionName": "The Rest Is Politics", "releaseDate": recent,
         "trackViewUrl": "https://pod/1"},
        {"trackName": "Unrelated episode", "collectionName": "X", "releaseDate": recent, "trackViewUrl": "https://pod/2"},
        {"trackName": "Keir Starmer, 2024", "collectionName": "X", "releaseDate": old, "trackViewUrl": "https://pod/3"}]}}))
    [ep] = asyncio.run(chatter.podcasts(STARMER))
    assert ep["url"] == "https://pod/1" and ep["interview"] and ep["platform"] == "Podcast"


def test_interview_headlines():
    for t in ["Jensen Huang interview: AI is here", "Starmer sits down with Laura Kuenssberg", "Dimon on CNBC: rates",
              "Merz speech in Berlin", "Musk podcast appearance"]:
        assert chatter.is_interview(t), t
    assert not chatter.is_interview("Starmer's seat goes to Labour")


def test_discussion_counts_and_threads_without_user_posts(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.setattr(chatter, "fetch_text", _fake({
        "hn.algolia": {"nbHits": 12, "hits": [
            {"_tags": ["story"], "title": "Starmer's AI plan", "objectID": "9", "points": 50, "num_comments": 30,
             "created_at_i": int(NOW - 600)},
            {"_tags": ["comment"], "comment_text": "This is a great and excellent plan", "objectID": "10"}]},
        "bsky.app": {"posts": [{"record": {"text": "terrible awful decision"}}] * 3}}))
    d = asyncio.run(chatter.discussion(STARMER))
    assert d["platforms"]["Hacker News"]["mentions"] == 12 and d["platforms"]["Bluesky"]["mentions"] == 3
    assert d["total"] == 15 and "Reddit" not in d["platforms"]
    [t] = d["threads"]
    assert t == {"platform": "Hacker News", "title": "Starmer's AI plan", "url": "https://news.ycombinator.com/item?id=9",
                 "score": 50, "comments": 30, "published": float(int(NOW - 600))}
    assert "text" not in json.dumps(d["threads"])  # no user posts are kept


def test_reddit_is_off_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert not chatter.reddit_enabled()
    assert asyncio.run(chatter.reddit("Keir Starmer")) is None


def test_reddit_with_credentials_keeps_threads_not_usernames(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")

    async def token():
        return "t"

    class Resp:
        def json(self):
            return {"data": {"children": [
                {"data": {"title": "Starmer resigns as MP", "subreddit_name_prefixed": "r/ukpolitics", "author": "someone",
                          "permalink": "/r/ukpolitics/comments/abc/", "score": 900, "num_comments": 400,
                          "created_utc": NOW - 3600, "over_18": False}}]}}

    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            assert kw["headers"]["Authorization"] == "bearer t"
            return Resp()
    monkeypatch.setattr(chatter, "_reddit_auth", token)
    monkeypatch.setattr(chatter.httpx, "AsyncClient", Client)
    r = asyncio.run(chatter.reddit("Keir Starmer"))
    assert r["summary"]["mentions"] == 1 and r["summary"]["comments"] == 400
    [t] = r["threads"]
    assert t["url"] == "https://www.reddit.com/r/ukpolitics/comments/abc/" and t["subreddit"] == "r/ukpolitics"
    assert "someone" not in json.dumps(r)


def test_statements_merge_gdelt_without_duplicates_and_tag_interviews(monkeypatch):
    recent = formatdate(NOW - 3600)
    google = f"""<rss><channel>
      <item><title>Starmer speaks - BBC</title><link>https://g/1</link><source>BBC</source><pubDate>{recent}</pubDate></item>
      <item><title>Keir Starmer interview: what next - Times</title><link>https://g/2</link><pubDate>{recent}</pubDate></item>
    </channel></rss>"""
    monkeypatch.setattr(sources, "fetch_text", _fake({"news.google": google}))
    monkeypatch.setattr(chatter, "fetch_text", _fake({"gdeltproject": {"articles": [
        {"url": "https://a/1", "title": "Starmer speaks", "domain": "bbc.co.uk", "seendate": STAMP.strftime("%Y%m%dT%H%M%SZ")},
        {"url": "https://a/2", "title": "Starmer in Brussels", "domain": "ft.com", "seendate": STAMP.strftime("%Y%m%dT%H%M%SZ")}]},
        "itunes": {"results": []}}))
    items, status = asyncio.run(sources.statements({"name": "Keir Starmer"}))
    titles = sorted(i["title"] for i in items)
    assert titles == ["Keir Starmer interview: what next - Times", "Starmer in Brussels", "Starmer speaks - BBC"]
    assert next(i for i in items if "interview" in i["title"])["interview"]
    assert status["provider"].startswith("Google News RSS + GDELT")


def test_gdelt_backs_off_after_a_refusal(monkeypatch):
    calls = []

    async def refuse(url, **kw):
        calls.append(url)
        return None  # 429
    monkeypatch.setattr(chatter, "fetch_text", refuse)
    monkeypatch.setitem(chatter._gdelt_state, "next", 0.0)
    assert asyncio.run(chatter.gdelt(STARMER)) == []
    assert asyncio.run(chatter.gdelt(STARMER)) == []  # backing off: no second request
    assert len(calls) == 1 and chatter._gdelt_state["next"] > time.time() + 50
    assert chatter.gdelt_status()["backing_off"] and chatter.gdelt_status()["refusals_in_a_row"] >= 1
    monkeypatch.setitem(chatter._gdelt_state, "next", 0.0)
    asyncio.run(chatter.gdelt(STARMER))
    assert chatter._gdelt_state["next"] > time.time() + 100  # the second refusal waits twice as long
    monkeypatch.setitem(chatter._gdelt_state, "next", 0.0)
    monkeypatch.setitem(chatter._gdelt_state, "refusals", 0)
