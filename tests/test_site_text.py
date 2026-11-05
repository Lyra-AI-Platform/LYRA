"""Things that must stay true of the site's own files."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBSITE = ROOT / "website"


def pages():
    return [p for p in WEBSITE.rglob("*.html")]


def test_tremor_has_one_address():
    for page in pages():
        text = page.read_text(errors="ignore")
        assert not re.search(r'href="/market[?"]', text), page
        assert not re.search(r'/market\?t(icker)?=', text), page


def test_people_have_real_addresses():
    for name in ("watch/index.html", "watch/live/index.html"):
        assert "#person/" not in (WEBSITE / name).read_text().replace("Old #person/ links", "")


def test_forgotten_password_goes_to_the_reset_page():
    login = (WEBSITE / "dashboard/login.html").read_text()
    assert 'href="forgot.html"' in login and "mailto:" not in login


def test_cloudflare_analytics_is_allowed():
    main = (ROOT / "lyra/main.py").read_text()
    assert "static.cloudflareinsights.com" in main and "https://cloudflareinsights.com" in main


def test_widget_finds_its_api_from_its_own_address():
    widget = (ROOT / "lyra/authenticator/frontend/lyraauth.js").read_text()
    assert "document.currentScript" in widget
    for name in ("data-callback", "data-expired-callback"):
        assert name in widget
