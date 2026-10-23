"""Sign in with Google / Apple / GitHub (lyra/api/oauth_api.py), against fake providers: the
round trip only works in the browser that started it, unverified emails are refused, a
provider never takes over a password account, and provider-only accounts can set a password."""
import os
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-oauth-test-"))
os.environ["LYRA_INSECURE_COOKIES"] = "1"
os.environ["LYRA_PUBLIC_URL"] = "http://testserver"

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import oauth_api, ratelimit, users_api  # noqa: E402
from lyra.db.models import OAuthIdentity, User  # noqa: E402
from _watchdb import make_app  # noqa: E402

SITE = "http://testserver"
PASSWORD = "plum kettle orbit 7"


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeProvider:
    """Stands in for the provider's token and user endpoints."""
    def __init__(self):
        self.claims = {}
        self.github_emails = []
        self.posted = []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, data=None, headers=None):
        self.posted.append((url, data))
        if "github" in url:
            return FakeResponse({"access_token": "gh-token"})
        return FakeResponse({"id_token": jwt.encode(self.claims, "irrelevant", algorithm="HS256")})

    def get(self, url, headers=None):
        if url.endswith("/user"):
            return FakeResponse({"id": 4242, "login": "octo", "name": "Octo Cat"})
        return FakeResponse(self.github_emails)


@pytest.fixture
def app(monkeypatch):
    ratelimit.reset()
    for k, v in {"GOOGLE_CLIENT_ID": "gid", "GOOGLE_CLIENT_SECRET": "gsecret",
                 "GITHUB_CLIENT_ID": "hid", "GITHUB_CLIENT_SECRET": "hsecret"}.items():
        monkeypatch.setenv(k, v)
    for k in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY", "APPLE_PRIVATE_KEY_FILE"):
        monkeypatch.delenv(k, raising=False)
    fake = FakeProvider()
    monkeypatch.setattr(oauth_api, "http_client", fake)
    app, Session = make_app(users_api.router, oauth_api.router)
    app.state.Session, app.state.fake = Session, fake
    return app


def _browser(app):
    return TestClient(app, headers={"Origin": SITE}, follow_redirects=False)


def _start(c, provider="google", **params):
    r = c.get(f"/api/oauth/{provider}/start", params=params)
    assert r.status_code == 303, r.text
    return parse_qs(urlsplit(r.headers["location"]).query)


def _google_claims(app, q, **over):
    claims = {"iss": "https://accounts.google.com", "aud": "gid", "exp": int(time.time()) + 300,
              "sub": "g-123", "email": "ada@example.com", "email_verified": True, "name": "Ada L",
              "nonce": q["nonce"][0]}
    claims.update(over)
    app.state.fake.claims = claims


def test_providers_reports_what_is_set_up(app):
    assert _browser(app).get("/api/oauth/providers").json() == {"google": True, "github": True, "apple": False}


def test_unconfigured_provider_goes_back_with_a_reason(app):
    r = _browser(app).get("/api/oauth/apple/start")
    assert r.status_code == 303 and "error=unavailable" in r.headers["location"]


def test_start_uses_pkce_state_and_nonce(app):
    q = _start(_browser(app), next="/market")
    assert q["code_challenge_method"] == ["S256"] and q["state"] and q["nonce"]
    assert q["redirect_uri"] == ["http://testserver/api/oauth/google/callback"]


def test_google_sign_up_creates_an_account_and_session(app):
    c = _browser(app)
    q = _start(c, next="/market")
    _google_claims(app, q)
    r = c.get("/api/oauth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert r.status_code == 303 and r.headers["location"] == "/market"
    assert c.get("/api/users/me").json()["email"] == "ada@example.com"
    # PKCE verifier went to the token endpoint.
    assert app.state.fake.posted[0][1]["code_verifier"]
    # Second sign-in finds the same account by subject, not a new one.
    c2 = _browser(app)
    q2 = _start(c2)
    _google_claims(app, q2, email="renamed@example.com")
    c2.get("/api/oauth/google/callback", params={"state": q2["state"][0], "code": "abc"})
    assert c2.get("/api/users/me").json()["email"] == "ada@example.com"
    s = app.state.Session()
    assert s.query(User).count() == 1
    s.close()


def test_callback_in_another_browser_is_refused(app):
    q = _start(_browser(app))
    _google_claims(app, q)
    attacker = _browser(app)
    r = attacker.get("/api/oauth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert "error=expired" in r.headers["location"]
    assert attacker.get("/api/users/me").status_code == 401


def test_wrong_state_nonce_or_audience_is_refused(app):
    for over, state_ok in (({}, False), ({"nonce": "other"}, True), ({"aud": "someone-else"}, True),
                           ({"iss": "https://evil.example"}, True), ({"exp": int(time.time()) - 600}, True)):
        c = _browser(app)
        q = _start(c)
        _google_claims(app, q, **over)
        state = q["state"][0] if state_ok else "forged"
        r = c.get("/api/oauth/google/callback", params={"state": state, "code": "abc"})
        assert "error=" in r.headers["location"], over
        assert c.get("/api/users/me").status_code == 401, over


def test_unverified_email_is_not_used(app):
    c = _browser(app)
    q = _start(c)
    _google_claims(app, q, email_verified=False)
    r = c.get("/api/oauth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert "error=no_email" in r.headers["location"]


def test_provider_never_takes_over_a_password_account(app):
    owner = _browser(app)
    assert owner.post("/api/users/register", json={"email": "ada@example.com", "password": PASSWORD}).status_code == 201
    c = _browser(app)
    q = _start(c)
    _google_claims(app, q)
    r = c.get("/api/oauth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert "error=link_required" in r.headers["location"]
    assert c.get("/api/users/me").status_code == 401


def test_signed_in_user_can_connect_and_disconnect(app):
    c = _browser(app)
    c.post("/api/users/register", json={"email": "ada@example.com", "password": PASSWORD})
    q = _start(c, link=1)
    _google_claims(app, q, email="ada.personal@gmail.com")
    r = c.get("/api/oauth/google/callback", params={"state": q["state"][0], "code": "abc"})
    assert r.headers["location"] == "/account/?connected=google"
    info = c.get("/api/oauth/identities").json()
    assert info["has_password"] and [x["provider"] for x in info["connected"]] == ["google"]
    assert c.delete("/api/oauth/google").status_code == 200


def test_github_uses_the_primary_verified_email(app):
    app.state.fake.github_emails = [{"email": "old@example.com", "primary": False, "verified": True},
                                    {"email": "octo@example.com", "primary": True, "verified": True}]
    c = _browser(app)
    q = _start(c, "github")
    r = c.get("/api/oauth/github/callback", params={"state": q["state"][0], "code": "abc"})
    assert r.status_code == 303 and "error" not in r.headers["location"]
    me = c.get("/api/users/me").json()
    assert me["email"] == "octo@example.com" and me["name"] == "Octo Cat"


def test_provider_only_account_sets_a_password_and_keeps_one_way_in(app):
    c = _browser(app)
    q = _start(c)
    _google_claims(app, q)
    c.get("/api/oauth/google/callback", params={"state": q["state"][0], "code": "abc"})
    # Can't log in with a password it doesn't have, and can't remove its only sign-in.
    assert _browser(app).post("/api/users/login", json={"email": "ada@example.com", "password": users_api.NO_PASSWORD}).status_code == 401
    assert c.delete("/api/oauth/google").status_code == 400
    # Setting a first password needs no current password.
    assert c.post("/api/users/password", json={"new_password": PASSWORD}).status_code == 200
    assert _browser(app).post("/api/users/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code == 200
    assert c.delete("/api/oauth/google").status_code == 200
    s = app.state.Session()
    assert s.query(OAuthIdentity).count() == 0
    s.close()


def test_open_redirects_are_refused(app):
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example"):
        assert oauth_api._safe_next(bad) == "/"
    assert oauth_api._safe_next("/watch/live/?x=1") == "/watch/live/?x=1"


def test_honeypot_blocks_bots(app):
    r = _browser(app).post("/api/users/register", json={"email": "bot@example.com", "password": PASSWORD, "website": "spam"})
    assert r.status_code == 400
