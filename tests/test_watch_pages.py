from lyra.watch import pages

PAGE = """<head><title>Lyra Watch</title><meta name="description" content="x" /><link rel="canonical" href="https://lyraauth.com/watch/" />
<meta property="og:title" content="x" /><meta property="og:description" content="x" /><meta property="og:url" content="x" /></head>"""


def test_a_profile_has_its_own_labels():
    out = pages.render(PAGE, {"id": "nancy-pelosi", "name": "Nancy Pelosi", "job": "US Representative"})
    assert "<title>Nancy Pelosi — Lyra Watch</title>" in out
    assert 'rel="canonical" href="https://lyraauth.com/watch/nancy-pelosi"' in out
    assert 'name="lyra-person" content="nancy-pelosi"' in out and "US Representative" in out


def test_names_from_the_news_are_escaped():
    out = pages.render(PAGE, {"id": "x", "name": '<script>"bad', "job": ""})
    assert "<script>" not in out


def test_sitemap_lists_each_person_once_and_skips_blanks():
    xml = pages.sitemap(["a-b", "a-b", "", None or ""])
    assert xml.count("<loc>") == 1 and "/watch/a-b<" in xml


def test_recent_trades_only():
    p = {"moves": [{"type": "statement", "title": "s", "date": "2026-09-01"}, {"type": "trade", "title": "old", "date": "2026-01-01"},
                   {"type": "trade", "title": "new", "date": "2026-10-01", "url": "u"}]}
    assert [t["title"] for t in pages.trades_of(p)] == ["new", "old"]
    assert pages.trades_of(None) == []
