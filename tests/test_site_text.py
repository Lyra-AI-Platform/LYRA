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


def test_every_page_has_the_basics():
    for page in pages():
        if page.parent.name == "admin":
            continue
        text = page.read_text(errors="ignore")
        assert 'name="description"' in text, page
        assert 'class="skip-link"' in text, page
        if page.parent.name != "share":
            assert 'rel="canonical"' in text and 'property="og:title"' in text, page


def test_skip_links_have_somewhere_to_go():
    for page in pages():
        text = page.read_text(errors="ignore")
        if 'class="skip-link"' in text:
            assert 'id="main"' in text, page


def test_pricing_means_the_pricing_page():
    for page in pages():
        if page.parent.name != "slabsign":
            assert "index.html#pricing" not in page.read_text(errors="ignore"), page


def test_the_plans_on_the_pricing_and_billing_pages():
    for name in ("pricing/index.html", "dashboard/billing.html"):
        text = (WEBSITE / name).read_text()
        for needed in ("£12", "£18", "Markets Pro", "Watch Pro", "1 Tremor reading a day"):
            assert needed in text, (name, needed)


def test_every_plan_price_is_in_pounds():
    for name in ("pricing/index.html", "dashboard/billing.html", "index.html", "watch/account/index.html"):
        text = (WEBSITE / name).read_text()
        assert not re.search(r'class="(price|plan-price|price-amount)"[^>]*>\$', text), name
