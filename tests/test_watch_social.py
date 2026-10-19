"""Official accounts, their free feeds, and posts reported by the news. Network calls are faked."""
import asyncio
import os
import tempfile

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-social-test-"))

from lyra.market import news  # noqa: E402
from lyra.watch import service, sources  # noqa: E402

YT = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>President Trump speaks</title>
<link href="https://www.youtube.com/watch?v=1"/><published>2026-10-18T10:00:00Z</published></entry></feed>"""
BSKY = """<rss><channel><item><link>https://bsky.app/profile/x/post/1</link>
<description>Congress must ban stock trading by members. Full stop.</description>
<pubDate>Sun, 18 Oct 2026 20:30:00 +0000</pubDate></item></channel></rss>"""


def test_posts_without_titles_use_their_text():
    [item] = news.parse_feed(BSKY)
    assert item["title"] == "Congress must ban stock trading by members. Full stop."


def test_account_links_cover_every_platform_but_read_only_free_ones():
    links = sources.account_links({"x": ["elonmusk"], "youtube": ["UCAql2DyGU2un1Ei2nMYsqOA"],
                                   "mastodon": ["user@mastodon.social"], "instagram": ["kimkardashian"]})
    by = {l["platform"]: l for l in links}
    assert by["x"] == {"platform": "x", "handle": "elonmusk", "url": "https://x.com/elonmusk", "read": False}
    assert by["youtube"]["read"] and by["mastodon"]["url"] == "https://mastodon.social/@user"
    assert not by["instagram"]["read"]


def test_own_feeds_keep_only_working_feeds(monkeypatch):
    async def fake_fetch(url, **kw):
        if "youtube" in url:
            return YT
        if "khanna" in url and "bsky" in url:
            return BSKY
        if url == "https://khanna.house.gov":
            return '<link rel="alternate" type="application/rss+xml" href="/rss.xml">'
        if url == "https://khanna.house.gov/rss.xml":
            return BSKY
        return None  # dead handle
    monkeypatch.setattr(sources, "fetch_text", fake_fetch)
    person = {"name": "Ro Khanna"}
    feeds = asyncio.run(sources.own_feeds(person, {
        "youtube": ["UCAql2DyGU2un1Ei2nMYsqOA", "not-a-channel"], "bluesky": ["khanna.house.gov", "dead.bsky.social"],
        "website": ["https://khanna.house.gov", "https://dell.com"]}))
    assert [(f["platform"], f["url"]) for f in feeds] == [
        ("YouTube", "https://www.youtube.com/feeds/videos.xml?channel_id=UCAql2DyGU2un1Ei2nMYsqOA"),
        ("Bluesky", "https://bsky.app/profile/khanna.house.gov/rss"),
        ("Website", "https://khanna.house.gov/rss.xml")]  # dell.com isn't his own site, so it isn't read


def test_reported_platform():
    assert sources.reported_platform("Musk tweeted a meme about Tesla") == "X"
    assert sources.reported_platform("Trump says on Truth Social that tariffs rise") == "Truth Social"
    assert sources.reported_platform("Kim Kardashian Instagram post sparks debate") == "Instagram"
    assert sources.reported_platform("A statement to reporters") == "Social media"


def test_statements_mark_own_posts_and_reported_posts(monkeypatch):
    coverage = """<rss><channel>
      <item><title>Ro Khanna tweeted support for the bill - CNN</title><link>https://cnn/1</link><source>CNN</source></item>
      <item><title>Ro Khanna holds town hall - AP</title><link>https://ap/1</link><source>AP</source></item></channel></rss>"""

    async def fake_fetch(url, **kw):
        if "bsky" in url:
            return BSKY
        return coverage
    monkeypatch.setattr(sources, "fetch_text", fake_fetch)
    items, status = asyncio.run(sources.statements(
        {"name": "Ro Khanna", "feeds": [{"platform": "Bluesky", "url": "https://bsky.app/profile/k/rss"}]}))
    by = {it["url"]: it for it in items}
    assert by["https://bsky.app/profile/x/post/1"]["own_words"] and by["https://bsky.app/profile/x/post/1"]["platform"] == "Bluesky"
    assert by["https://cnn/1"]["reported"] and by["https://cnn/1"]["platform"] == "X"
    assert not by["https://ap/1"].get("reported") and not by["https://ap/1"]["own_words"]
    assert status["provider"] == "Google News RSS + own feeds"


def test_profile_carries_accounts_and_posts(monkeypatch):
    async def fake_wiki(person):
        return {"status": "ok", "qid": "Q1"}

    async def fake_wd(qid):
        return {"accounts": {"x": ["RoKhanna"], "bluesky": ["khanna.house.gov"], "website": ["https://khanna.house.gov"]}}

    async def fake_feeds(person, accounts):
        return [{"platform": "Bluesky", "url": "https://bsky.app/profile/khanna.house.gov/rss", "posts": 1}]

    async def fake_statements(person, max_age=0):
        assert person["feeds"][0]["platform"] == "Bluesky"
        return ([{"title": "Ban member stock trading", "summary": "", "url": "https://bsky.app/p/1", "source": "bsky.app",
                  "published": 1.79e9, "own_words": True, "platform": "Bluesky"}], {"status": "ok"})
    monkeypatch.setattr(sources, "wiki_person", fake_wiki)
    monkeypatch.setattr(sources, "wikidata_profile", fake_wd)
    monkeypatch.setattr(sources, "own_feeds", fake_feeds)
    monkeypatch.setattr(sources, "statements", fake_statements)
    p = asyncio.run(service.build_profile({"slug": "ro-khanna", "name": "Ro Khanna", "role": "Rep"}))
    assert {a["platform"]: a["read"] for a in p["accounts"]} == {"x": False, "bluesky": True, "website": False}
    assert p["posts"][0]["platform"] == "Bluesky" and p["media"][0]["own_words"]
    assert p["summary"]["tone"]["own_words"]["items"] == 1


def test_only_headlines_about_posts_count_as_reported_posts():
    rx = sources._POST_HEADLINE
    for t in ["Musk tweeted a meme", "Trump says on Truth Social tariffs rise", "Kardashian Instagram post goes viral",
              "Pelosi writes on X that the bill is dead", "Swift's TikTok video breaks records"]:
        assert rx.search(t), t
    for t in ["Elon Musk proposes high-speed Hyperloop", "Sam Altman praises Elon Musk on Tesla's Roadster",
              "X Corp sues advertisers"]:
        assert not rx.search(t), t


def test_bluesky_embed_marker_is_removed():
    body = BSKY.replace("Full stop.", "Full stop.\n\n[contains quote post or other embedded content]")
    assert news.parse_feed(body)[0]["title"] == "Congress must ban stock trading by members. Full stop."
