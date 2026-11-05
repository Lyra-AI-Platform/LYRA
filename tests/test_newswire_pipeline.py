"""The pipeline every product reads: tags, clusters, Breaking and per-company counts."""
import time

import pytest

from lyra.newswire import clusters as CL
from lyra.newswire.store import WireStore
from lyra.newswire.tagging import item_id, tagger


def story(n, title, source, when, **tags):
    url = f"https://{source}/{n}"
    return {"id": item_id(url), "url": url, "title": title, "source": source, "published": when, **tags}


@pytest.fixture
def wire(tmp_path):
    return WireStore(tmp_path / "wire.db")


def test_the_same_story_from_many_outlets_is_one_cluster(wire):
    now = time.time() - 600
    wire.add([story(1, "Nvidia shares fall after China export curbs announced - Reuters", "reuters.com", now),
              story(2, "Nvidia shares fall after new China export curbs", "bbc.co.uk", now + 60),
              story(3, "Bank of Japan holds interest rates steady in October meeting", "nhk.jp", now + 90)])
    rows = wire.clusters()
    assert sorted(c["stories"] for c in rows) == [1, 2]
    nvidia = next(c for c in rows if c["stories"] == 2)
    assert nvidia["outlets"] == 2


def test_duplicates_count_once(wire):
    now = time.time()
    a = story(1, "Oil prices climb as OPEC agrees deeper output cuts", "a.example", now)
    assert wire.add([a, a]) == 1
    assert wire.add([a]) == 0
    assert wire.clusters()[0]["stories"] == 1


@pytest.mark.parametrize("gaps,broke", [([0, 300, 900], True), ([0, 300, 901], False), ([0, 5000, 5100, 5200], True), ([0, 10], False)])
def test_breaking_needs_three_outlets_in_fifteen_minutes(gaps, broke):
    assert (CL.breaking_time(gaps) is not None) is broke


def test_breaking_badge_comes_from_real_outlets(wire):
    now = time.time() - 300
    title = "Federal Reserve cuts interest rates by half point in surprise move"
    wire.add([story(1, title, "a.example", now), story(2, title, "b.example", now + 120)])
    assert not wire.clusters()[0]["breaking"]
    wire.add([story(3, title, "c.example", now + 240)])
    assert wire.clusters()[0]["breaking"]


def test_one_outlet_repeating_itself_is_not_breaking(wire):
    now = time.time() - 300
    title = "Federal Reserve cuts interest rates by half point in surprise move"
    wire.add([story(i, title, "a.example", now + i) for i in range(5)])
    assert not wire.clusters()[0]["breaking"]


def test_tags_merge_and_every_product_can_filter_on_them(wire):
    now = time.time() - 100
    wire.add([story(1, "Tesla recalls thousands of electric vehicles over brake fault", "a.example", now,
                    tickers=["TSLA"], topics=["markets"]),
              story(2, "Tesla recalls thousands of electric vehicles after brake fault found", "b.example", now + 5,
                    people=["Elon Musk"])])
    c = wire.clusters({"tickers": "TSLA"})[0]
    assert c["people"] == ["Elon Musk"] and c["tickers"] == ["TSLA"]
    assert "people" in c["channels"] and "markets" in c["channels"]
    assert wire.clusters({"channel": "people"}) and not wire.clusters({"channel": "energy"})


def test_importance_favours_breadth(wire):
    now = time.time() - 1000
    wire.add([story(i, "Boeing wins huge defence contract from Pentagon this week", f"o{i}.example", now + i * 3600 / 8) for i in range(5)])
    wire.add([story(9, "Local bakery opens second shop near the station today", "z.example", now)])
    assert wire.clusters(by_importance=True)[0]["title"].startswith("Boeing")


def test_company_counts(wire):
    now = time.time() - 60
    wire.add([story(1, "Pfizer wins approval for new vaccine", "a.example", now, tickers=["PFE"]),
              story(2, "Unrelated Pfizer lawsuit moves forward in Delaware", "b.example", now, tickers=["PFE"]),
              story(3, "Pfizer older note about something else entirely today", "a.example", now - 3 * 86400, tickers=["PFE"])])
    a = wire.activity()["PFE"]
    assert (a["day"], a["week"], a["outlets"]) == (2, 3, 2)
    assert wire.stories_since("PFE", time.time() - 7 * 86400) == 3


def test_spikes_carry_their_headline(wire):
    now = time.time() - 60
    wire.add([story(i, "AMD surges as data centre revenue doubles", f"o{i}.example", now, tickers=["AMD"]) for i in range(4)])
    spike = wire.spikes("AMD", now - 86400)[0]
    assert spike["stories"] == 4 and spike["title"].startswith("AMD surges")


def test_articles_stored_before_the_pipeline_are_brought_in(wire):
    now = time.time() - 60
    wire.add([story(1, "Shell profits beat forecasts on strong gas trading", "a.example", now, tickers=["SHEL"])])
    with wire._lock:
        wire._conn.execute("UPDATE wire SET cluster=''")
        wire._conn.executescript("DELETE FROM cluster; DELETE FROM ticker_hour; DELETE FROM ticker_outlet; DELETE FROM cluster_outlet;")
    wire._index = CL.ClusterIndex()
    assert wire.backfill() == 1
    assert wire.backfill() == 0
    assert wire.activity()["SHEL"]["day"] == 1


def test_bringing_old_articles_in_corrects_their_tags(wire):
    now = time.time() - 60
    wire.add([story(1, "Oil climbs on supply fears - Google News", "a.example", now, tickers=["GOOGL"])])
    with wire._lock:
        wire._conn.execute("UPDATE wire SET cluster=''")
        wire._conn.executescript("DELETE FROM cluster; DELETE FROM ticker_hour; DELETE FROM ticker_outlet; DELETE FROM cluster_outlet;")
    wire._index = CL.ClusterIndex()
    wire.backfill(retag=tagger.tag)
    assert "GOOGL" not in wire.activity()
    assert wire.search({})["results"][0]["tickers"] == []


def test_clusters_survive_a_restart(tmp_path):
    now = time.time() - 60
    w = WireStore(tmp_path / "wire.db")
    w.add([story(1, "Airbus delivers record number of jets this quarter", "a.example", now)])
    w._conn.close()
    w = WireStore(tmp_path / "wire.db")
    w.add([story(2, "Airbus delivers record number of jets in the quarter", "b.example", now + 1)])
    assert w.clusters()[0]["stories"] == 2


def test_topics_for_every_product_are_tagged():
    t = tagger.tag({"title": "New tariff on Nvidia chips as the central bank warns on inflation", "language": "en"})
    assert {"trade-policy", "central-banks"} <= set(t["topics"]) and "NVDA" in t["tickers"]
