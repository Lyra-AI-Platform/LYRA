"""Which ad each place shows: sponsor first, then one Google unit (only where allowed), then
Lyra's own offer; the homepage never shows Google or house ads."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lyra.api import adsense, ads_api  # noqa: E402


class S:
    id, headline, body = 7, "Great tool", "Try it"


NET = {"client": "ca-pub-1234567890123456", "slot": "123"}


def test_sponsor_beats_everything():
    for place in ("watch", "news", "tremor", "home"):
        assert ads_api.choose(place, [S()], NET)["kind"] == "sponsor"


def test_google_only_on_allowed_pages():
    assert ads_api.choose("news", [], NET)["kind"] == "network"
    assert ads_api.choose("home", [], NET)["kind"] == "none"
    assert ads_api.choose("news", [], None)["kind"] == "house"
    assert ads_api.choose("home", [], None)["kind"] == "none"


def test_google_script_scope(monkeypatch):
    monkeypatch.setenv("LYRA_ADSENSE_CLIENT", NET["client"])
    monkeypatch.delenv("LYRA_ADSENSE_SLOT", raising=False)
    assert adsense.unit() is None and not adsense.loads_script("/news/")
    monkeypatch.setenv("LYRA_ADSENSE_SLOT", "123")
    assert adsense.loads_script("/news/") and adsense.loads_script("/watch/elon-musk")
    assert not adsense.loads_script("/") and not adsense.loads_script("/pages/lyraauth.html")
    assert b"adsbygoogle" not in adsense.head_tags(script=False)


def test_on_by_default_and_switchable(monkeypatch):
    monkeypatch.delenv("LYRA_ADSENSE_CLIENT", raising=False)
    assert adsense.client() == adsense.PUBLISHER and "pub-4940586207754938" in adsense.ads_txt()
    monkeypatch.setenv("LYRA_ADSENSE_CLIENT", "off")
    assert adsense.client() is None and adsense.ads_txt() is None
