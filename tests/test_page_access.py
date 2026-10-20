"""Members-only pages are withheld on the server (lyra/api/page_access.py): signed out, on an
ended trial, without Watch Pro, or by spelling the path differently, the page never arrives."""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-page-test-"))
os.environ["LYRA_INSECURE_COOKIES"] = "1"   # the test client talks plain http

import pytest  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import page_access, ratelimit, users_api  # noqa: E402
from lyra.api.users_api import _create_token  # noqa: E402
from lyra.db.models import User  # noqa: E402
from _watchdb import make_app  # noqa: E402

WEBSITE = Path(__file__).resolve().parent.parent / "website"


@pytest.fixture
def site(monkeypatch):
    ratelimit.reset()
    app, Session = make_app(users_api.router)
    monkeypatch.setattr(page_access, "session_factory", Session)
    app.middleware("http")(page_access.guard)

    @app.get("/market", response_class=HTMLResponse)
    def market():
        return "<h1>market</h1>"

    @app.get("/")
    def home(request: Request):
        return page_access.signed_in_home(request, WEBSITE) or HTMLResponse("<h1>MARKETING-PAGE</h1>")

    app.mount("/", StaticFiles(directory=str(WEBSITE), html=True), name="website")
    return app, Session


def _client(app, Session=None, tier="free", days_old=0, email=None):
    """A browser, signed in by cookie when a tier is given."""
    c = TestClient(app, follow_redirects=False)
    if Session:
        s = Session()
        u = User(email=email or f"{tier}{days_old}-{id(c)}@example.com", password_hash="x", tier=tier,
                 created_at=datetime.now(timezone.utc) - timedelta(days=days_old))
        s.add(u)
        s.commit()
        c.cookies.set(users_api.SESSION_COOKIE, _create_token(u.id))
        s.close()
    return c


PUBLIC = ["/pages/privacy.html", "/pages/docs.html", "/watch/", "/tremor/", "/company/", "/dashboard/login.html"]
MEMBERS = ["/coshh/", "/dashboard/chat.html", "/market"]


@pytest.mark.parametrize("path", PUBLIC)
def test_public_pages_stay_open(site, path):
    app, _ = site
    assert _client(app).get(path).status_code == 200


@pytest.mark.parametrize("path", MEMBERS + ["/dashboard/", "/dashboard/billing.html", "/home/", "/watch/live/"])
def test_signed_out_visitors_are_sent_to_sign_in(site, path):
    app, _ = site
    r = _client(app).get(path)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/dashboard/login.html?next=")
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["//coshh/", "/coshh/index.html", "/x/../coshh/", "/COSHH/", "/coshh//index.html",
                                  "/dashboard//chat.html", "/watch//live/", "/%63oshh/"])
def test_other_spellings_of_a_locked_path_are_locked_too(site, path):
    app, _ = site
    assert _client(app).get("http://testserver" + path).status_code in (303, 404)


def test_the_api_behind_a_product_answers_401_not_a_redirect(site):
    app, _ = site
    r = _client(app).get("/api/coshh/search?q=acetone")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "sign_in_required"


@pytest.mark.parametrize("path", MEMBERS)
def test_trial_users_get_in(site, path):
    app, Session = site
    assert _client(app, Session).get(path).status_code == 200


@pytest.mark.parametrize("path", MEMBERS)
def test_ended_trial_goes_to_billing(site, path):
    app, Session = site
    r = _client(app, Session, days_old=400).get(path)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/dashboard/billing.html?need=")
    # the account pages stay open so they can pay
    assert _client(app, Session, days_old=400).get("/dashboard/billing.html").status_code == 200


@pytest.mark.parametrize("tier", ["starter", "pro"])
def test_paid_plans_open_everything(site, tier):
    app, Session = site
    c = _client(app, Session, tier=tier, days_old=400)
    for path in MEMBERS + ["/watch/live/", "/home/"]:
        assert c.get(path).status_code == 200, path


def test_watch_live_needs_watch_pro(site):
    app, Session = site
    r = _client(app, Session).get("/watch/live/")
    assert r.status_code == 303
    assert r.headers["location"] == "/watch/account/?need=watch"


def test_owner_pages_are_invisible_to_everyone_else(site, monkeypatch):
    app, Session = site
    monkeypatch.setenv("LYRA_ADMIN_EMAILS", "owner@example.com")
    for c in (_client(app), _client(app, Session, tier="pro")):
        assert c.get("/fuelwise/").status_code == 404
        assert c.get("/fuelwise/drafts/notes.html").status_code == 404


def test_fuelwise_privacy_opens_from_its_link_but_is_never_listed(site):
    app, _ = site
    r = _client(app).get("/fuelwise/privacy/")
    assert r.status_code == 200
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["referrer-policy"] == "no-referrer"
    # no Lyra page links to it
    for page in WEBSITE.rglob("*.html"):
        if "fuelwise" not in page.parts:
            assert "/fuelwise/privacy" not in page.read_text(encoding="utf-8"), page
    assert "fuelwise" not in (WEBSITE / "sitemap.xml").read_text().lower()


def test_a_forged_or_expired_cookie_is_ignored(site):
    app, _ = site
    c = _client(app)
    c.cookies.set(users_api.SESSION_COOKIE, "not-a-token")
    assert c.get("/coshh/").status_code == 303


def test_sign_in_sets_the_cookie_and_the_homepage_changes(site):
    app, _ = site
    c = TestClient(app, follow_redirects=False)
    assert "MARKETING-PAGE" in c.get("/").text
    r = c.post("/api/users/register", json={"email": "new@example.com", "password": "correct horse 9"})
    assert r.status_code == 201
    set_cookie = r.headers.get_list("set-cookie")
    assert any(h.startswith("lyra_session=") and "HttpOnly" in h for h in set_cookie)
    home = c.get("/")
    assert home.status_code == 200 and "MARKETING-PAGE" not in home.text
    assert home.headers["cache-control"] == "no-store"
    assert c.get("/coshh/").status_code == 200
    c.post("/api/users/logout")
    assert "MARKETING-PAGE" in c.get("/").text
    assert c.get("/coshh/").status_code == 303


def test_signed_in_users_skip_the_sign_in_form_but_never_leave_the_site(site):
    app, Session = site
    c = _client(app, Session)
    assert c.get("/dashboard/login.html?next=/coshh/").headers["location"] == "/coshh/"
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example"):
        assert c.get("/dashboard/login.html", params={"next": bad}).headers["location"] == "/"
