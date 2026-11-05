"""Tremor on Newswire and Newswire on Tremor: stress, cards, signals and the timeline."""
import pytest

from lyra.market import pulse
from lyra.market.store import MarketStore


@pytest.mark.parametrize("stress,name", [(None, "unknown"), (54, "calm"), (55, "rising"), (69, "rising"), (70, "high")])
def test_levels(stress, name):
    assert pulse.level(stress) == name


@pytest.mark.parametrize("query,kind,value", [
    ("Nvidia", "company", "NVDA"), ("nvda", "company", "NVDA"), ("NVDA", "company", "NVDA"), ("novo", "company", "NVO"),
    ("chips", "sector", "semiconductors"), ("Pharma", "sector", "pharma"), ("tariffs", "sector", "trade-policy"),
])
def test_a_search_finds_its_company_or_sector(query, kind, value):
    found = pulse.resolve(query)
    assert found["kind"] == kind and (found.get("ticker") or found.get("topic")) == value


@pytest.mark.parametrize("query", ["", "the weather in barry", "ai " * 30, "USD"])
def test_other_searches_get_no_card(query):
    assert pulse.resolve(query) is None


def test_plain_english_only_says_what_the_data_shows():
    reading = {"stress": 72, "features": {"insider_flow": -0.6, "congress_flow": 0.02, "news_sentiment": -0.4}}
    text = pulse.plain_english("Nvidia", reading, {"available": True, "level": 18.25, "regime": "normal"})
    assert "stress is high at 72" in text and "insiders have been selling" in text
    assert "Politicians" not in text and "turned negative" in text and "18.2" in text


def test_no_reading_says_so():
    assert "no recent Tremor reading" in pulse.plain_english("Nvidia", None, None)


def test_sector_stress_averages_companies_with_readings():
    s = pulse.sector_stress("energy", {"XOM": {"stress": 60}, "CVX": {"stress": 80}})
    assert (s["stress"], s["level"], s["companies_read"]) == (70, "high", 2)
    assert pulse.sector_stress("pharma", {})["level"] == "unknown"


def test_a_signal_links_to_the_stories_behind_it():
    rows = [{"title": "Nvidia shares plunge on probe", "outlets": 9}, {"title": "Nvidia beats forecasts", "outlets": 2},
            {"title": "Senator trades Nvidia stock", "outlets": 3}]
    linked = pulse.link_signals([{"factor": "news_sentiment", "value": -0.5}, {"factor": "congress_flow", "value": -0.5},
                                 {"factor": "momentum", "value": 0.5}], rows)
    assert [a["title"] for a in linked[0]["articles"]] == ["Nvidia shares plunge on probe"]
    assert linked[1]["articles"][0]["title"].startswith("Senator")
    assert linked[2]["articles"] == []


def test_timeline_puts_news_and_stress_on_one_axis():
    day = 86400 * 20000
    t = pulse.timeline({day // 3600: 5, day // 3600 + 1: 7}, [{"ts": day + 10, "stress": 61}], [{"ts": day, "title": "x"}], day, day + 86400)
    assert t["days"][0] == {"ts": day, "stories": 12, "stress": 61}
    assert t["days"][1]["stress"] is None and t["pins"]


def test_a_spike_is_a_sharp_jump():
    assert pulse.is_spike(50, 65) and not pulse.is_spike(50, 64) and not pulse.is_spike(None, 90) and not pulse.is_spike(70, 40)


def test_stress_log_gives_latest_and_daily_change(tmp_path):
    import time
    s = MarketStore(tmp_path / "m.db")
    now = time.time()
    s.log_stress("nvda", 50, 50.0, {"insider_flow": -1}, ts=now - 86400)
    s.log_stress("NVDA", 66, 40.0, {"insider_flow": -1}, ts=now - 60)
    s.log_stress("OLD", 90, 40.0, {}, ts=now - 30 * 86400)
    latest = s.stress_latest()
    assert latest["NVDA"]["stress"] == 66 and latest["NVDA"]["change_24h"] == 16
    assert "OLD" not in latest
    assert len(s.stress_rows("NVDA", now - 7 * 86400)) == 2
