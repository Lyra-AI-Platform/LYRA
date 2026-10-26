"""Lyra Newswire (lyra/newswire): storage with full-text search and filters, tagging, and the
API's free taste versus full access. Nothing here touches the network."""
import os
import tempfile
import time

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-wire-test-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import wire_api  # noqa: E402
from lyra.db.models import WatchSubscription  # noqa: E402
from lyra.newswire import store as wire_store  # noqa: E402
from lyra.newswire.collector import item_id, tagger  # noqa: E402
from _watchdb import make_app, signed_in  # noqa: E402


@pytest.fixture
def wire(tmp_path, monkeypatch):
    w = wire_store.WireStore(tmp_path / "wire.db")
    monkeypatch.setattr(wire_store, "_store", w)
    return w


def _item(i, **kw):
    base = {"id": item_id(f"https://x.test/{i}"), "url": f"https://x.test/{i}", "title": f"Story {i}", "summary": "",
            "source": "x.test", "country": "GB", "language": "en", "kind": "news", "published": time.time() - i * 60}
    return {**base, **kw}


def test_duplicates_are_ignored_and_counted_once(wire):
    assert wire.add([_item(1), _item(2)]) == 2
    assert wire.add([_item(1), _item(3)]) == 1
    assert wire.stats()["articles"] == 3


def test_search_and_filters(wire):
    wire.add([_item(1, title="BASF opens battery electrolyte plant", topics=["chemicals"], tickers=["BASFY"], country="DE", language="de"),
              _item(2, title="New electrolyte doubles battery life", kind="research", topics=["chemicals"]),
              _item(3, title="Parliament debates chip tariffs", topics=["politics", "trade-policy"], tickers=["NVDA"], people=["Jane Doe"])])
    assert wire.search({"q": "electrolyte"})["total"] == 2
    assert wire.search({"q": "batt"})["total"] == 2            # prefix match on the last word
    assert [r["kind"] for r in wire.search({"q": "electrolyte", "kind": "research"})["results"]] == ["research"]
    assert wire.search({"country": "DE,FR"})["total"] == 1
    assert wire.search({"tickers": "nvda"})["results"][0]["people"] == ["Jane Doe"]
    assert wire.search({"topics": "politics", "people": "Jane Doe"})["total"] == 1
    assert wire.search({"since": time.time() + 60})["total"] == 0
    f = wire.facets({})
    assert {"value": "chemicals", "count": 2} in f["topics"] and f["country"][0]["value"] == "GB"


@pytest.mark.parametrize("q", ['"', "AND OR NOT", "x*", "NEAR(", "'; DROP TABLE wire; --", "∑∂ƒ", "a"])
def test_odd_searches_never_error(wire, q):
    wire.add([_item(1)])
    wire.search({"q": q})


def test_tagging_finds_topics_companies_and_avoids_false_friends():
    t = tagger.tag({"title": "Nvidia and TSMC shares fall as tariffs hit chipmakers", "language": "en"})
    assert {"NVDA", "TSM"} <= set(t["tickers"]) and {"semiconductors", "trade-policy"} <= set(t["topics"])
    assert tagger.tag({"title": "La meta del gobierno", "language": "es"})["tickers"] == []


def test_visitors_get_a_taste_members_get_everything(wire):
    wire.add([_item(i, title=f"Market story {i}") for i in range(40)])
    app, Session = make_app(wire_api.router)
    c = TestClient(app)
    free = c.get("/api/wire/search?q=market&limit=100&offset=20").json()
    assert len(free["results"]) == wire_api.FREE_RESULTS and free["locked"] == 30 and not free["full"]
    uid, pro = signed_in(Session, "free")
    s = Session()
    s.add(WatchSubscription(user_id=uid, status="active"))
    s.commit()
    full = c.get("/api/wire/search?q=market&limit=100&offset=20", headers=pro).json()
    assert full["full"] and len(full["results"]) == 20


def test_ticker_view_for_tremor(wire):
    wire.add([_item(1, title="Senator questions Nvidia export deal", topics=["politics"], tickers=["NVDA"], people=["Jane Doe"]),
              _item(2, title="Nvidia beats estimates", topics=["markets"], tickers=["NVDA"]),
              _item(3, title="New GPU memory paper", kind="research", tickers=["NVDA"])])
    app, _ = make_app(wire_api.router)
    d = TestClient(app).get("/api/wire/ticker/nvda").json()
    assert d["politics_and_policy"][0]["title"].startswith("Senator") and d["people_in_coverage"] == [["Jane Doe", 1]]
    assert d["news_total_30d"] == 2 and len(d["research"]) == 1


def test_app_headlines_are_free_recent_and_paged(wire):
    wire.add([_item(i, title=f"Headline {i}", topics=["politics"] if i % 2 else []) for i in range(50)])
    wire.add([_item(99, title="Old news", published=time.time() - 10 * 86400),
              _item(98, title="Headline 1", url="https://y.test/1", source="y.test")])   # syndicated copy
    app, _ = make_app(wire_api.router)
    c = TestClient(app)
    first = c.get("/api/wire/headlines?limit=30").json()
    assert len(first["results"]) == 30 and first["next"] == 30
    rest = c.get("/api/wire/headlines?limit=30&offset=30").json()
    titles = [r["title"] for r in first["results"] + rest["results"]]
    assert "Old news" not in titles and rest["next"] is None
    assert all("politics" in r["topics"] for r in c.get("/api/wire/headlines?topics=politics").json()["results"])


def test_related_coverage_skips_the_story_itself(wire):
    wire.add([_item(1, title="Strike shuts Rotterdam port terminals", source="a.test"),
              _item(2, title="Rotterdam port strike enters second day", source="b.test", country="NL", language="nl"),
              _item(3, title="Cake recipe of the week", source="c.test")])
    app, _ = make_app(wire_api.router)
    d = TestClient(app).get("/api/wire/related", params={"title": "Strike shuts Rotterdam port terminals", "source": "a.test"}).json()
    assert [r["source"] for r in d["results"]] == ["b.test"]
