import time

from lyra.market import live_events as E


def cluster(**kw):
    return {"id": "c1", "title": "Nvidia chips banned", "url": "https://a.example/1", "source": "a.example", "outlets": 4,
            "breaking_at": 100.0, "people": ["Elon Musk"], "tickers": ["NVDA"], "topics": ["ai"], **kw}


def test_breaking_event_has_what_live_needs():
    e = E.breaking_event(cluster())
    assert e["kind"] == "breaking" and e["feed"] == "4 outlets reporting" and e["companies"][0]["ticker"] == "NVDA"


def test_spike_event_carries_the_headlines_that_caused_it():
    e = E.spike_event("NVDA", "Nvidia", 50, 72, [cluster(), cluster(title="Second"), cluster(), cluster()])
    assert e["kind"] == "tremor_spike" and "from 50 to 72" in e["title"] and len(e["headlines"]) == 3


def test_spike_event_without_stories_still_works():
    assert E.spike_event("NVDA", "Nvidia", 50, 72, [])["url"] == ""


def test_follow_matching():
    c = cluster()
    assert E.matches({"kind": "person", "value": "Elon Musk"}, c)
    assert E.matches({"kind": "company", "value": "NVDA"}, c)
    assert E.matches({"kind": "topic", "value": "ai"}, c)
    assert E.matches({"kind": "search", "value": "chips BANNED"}, c)
    assert not E.matches({"kind": "company", "value": "AMD"}, c)


def test_alerts_are_opt_in_and_rate_limited():
    now = time.time()
    assert not E.may_alert({"alerts": False}, now)
    assert E.may_alert({"alerts": True, "last_alert": 0}, now)
    assert not E.may_alert({"alerts": True, "last_alert": now - 60}, now)


def test_watching_counts_recent_viewers_only():
    seen = {"a": 1000.0, "b": 900.0}
    assert E.viewers_online(seen, now=1100.0) == 1 and "b" not in seen
