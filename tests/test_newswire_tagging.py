"""Tagging and cleaning stories. None of this needs the network."""
import pytest

from lyra.newswire import tagging
from lyra.newswire.store import WireStore, safe_url


def tag(title, summary="", language="en"):
    return tagging.tagger.tag({"title": title, "summary": summary, "language": language})


def test_google_news_wrappers_are_not_alphabet_mentions():
    assert "GOOGL" not in tag("Oil climbs on supply fears - Google News")["tickers"]
    assert "GOOGL" not in tag("Oil climbs", "https://news.google.com/rss/articles/abc Read more")["tickers"]
    assert "GOOGL" in tag("Google fined by EU regulators")["tickers"]


@pytest.mark.parametrize("title", ["SpaceX fund $SPCX jumps", "Shares of NYSE: USD rise", "The $CEO letter"])
def test_fake_tickers_are_dropped(title):
    assert not tagging.C.BLOCKED_TICKERS & set(tag(title)["tickers"])


def test_real_cashtags_stay():
    assert "NVDA" in tag("Traders pile into $NVDA")["tickers"]


@pytest.mark.parametrize("name,code", [("Macedonian", "mk"), ("Croatian", "hr"), ("Serbian", "sr"), ("Bosnian", "bs"),
                                       ("Slovak", "sk"), ("Slovenian", "sl"), ("English", "en"), ("Klingon", ""), ("", "")])
def test_language_codes_are_real_codes(name, code):
    assert tagging.language_code(name) == code


@pytest.mark.parametrize("raw,clean", [("Oil rises , traders say .", "Oil rises, traders say."),
                                       ("Up 5 % ( so far )", "Up 5% (so far)"), ("Fine, thanks", "Fine, thanks")])
def test_stray_spaces_go(raw, clean):
    assert tagging.tidy_title(raw) == clean


@pytest.mark.parametrize("url,ok", [("https://a.example/x", True), ("HTTP://a.example", True), (" https://a.example", True),
                                    ("javascript:alert(1)", False), ("data:text/html,x", False), ("", False),
                                    ("//a.example/x", False)])
def test_only_web_links(url, ok):
    assert bool(safe_url(url)) is ok


def item(i, url):
    return {"id": i, "url": url, "title": f"story {i}", "published": 1000.0}


def test_unsafe_links_are_never_stored_or_served(tmp_path):
    w = WireStore(tmp_path / "wire.db")
    assert w.add([item("a", "javascript:alert(1)"), item("b", "https://ok.example/1")]) == 1
    with w._lock:
        w._conn.execute("INSERT INTO wire (id,url,title,published,fetched) VALUES ('old','javascript:x','old',1,1)")
        w._conn.commit()
    assert [r["id"] for r in w.search({})["results"]] == ["b"]


def test_old_language_codes_are_corrected_once(tmp_path):
    path = tmp_path / "wire.db"
    w = WireStore(path)
    w.add([{**item("a", "https://x.example/a"), "language": "cr", "via": "GDELT"}])
    with w._lock:
        w._conn.execute("PRAGMA user_version=0")
        w._conn.commit()
    w._conn.close()
    w = WireStore(path)
    assert w.search({})["results"][0]["language"] == "hr"
