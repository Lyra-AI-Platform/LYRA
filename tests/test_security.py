"""Security rules: engine control APIs are local-only, CORS carries no credentials, pages get
security headers, sign-in and sign-up are rate limited and validated, credits can't be overspent."""
import os
import tempfile

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-sec-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp(prefix='lyra-sec-db-')}/t.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import ratelimit, users_api, watch_access  # noqa: E402
from _watchdb import make_app, signed_in  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture(scope="module")
def site():
    from lyra import main
    return main


@pytest.mark.parametrize("path", ["/api/models/status", "/api/memory/stats", "/api/learning/status", "/api/owner/status",
                                  "/api/quantum/ibm/status", "/api/ingestion/status", "/openapi.json", "/docs"])
def test_engine_controls_are_hidden_from_the_internet(site, path):
    internet = TestClient(site.app, client=("203.0.113.9", 5000))
    assert internet.get(path).status_code == 404
    # Through the Cloudflare tunnel the connection comes from localhost, but with Cloudflare's headers.
    tunnel = TestClient(site.app, client=("127.0.0.1", 5000))
    assert tunnel.get(path, headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 404
    assert tunnel.post("/api/memory/clear", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 404


def test_engine_controls_still_work_on_the_machine_itself(site):
    local = TestClient(site.app, client=("127.0.0.1", 5000))
    assert local.get("/openapi.json").status_code == 200
    # Public routes are untouched.
    assert TestClient(site.app, client=("203.0.113.9", 5000)).get("/api/watch/account/pricing").status_code == 200


def test_cors_never_allows_credentials(site):
    r = TestClient(site.app).options("/api/watch/people", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-credentials") != "true"


def test_login_is_rate_limited_after_failed_attempts():
    app, Session = make_app(users_api.router)
    c = TestClient(app)
    for _ in range(10):
        assert c.post("/api/users/login", json={"email": "a@example.com", "password": "wrongpass"}).status_code == 401
    r = c.post("/api/users/login", json={"email": "a@example.com", "password": "wrongpass"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_register_validates_and_is_rate_limited(monkeypatch):
    monkeypatch.setenv("LYRA_ADMIN_EMAILS", "owner@example.com")
    app, _ = make_app(users_api.router)
    c = TestClient(app)
    assert c.post("/api/users/register", json={"email": "not-an-email", "password": "longenough"}).status_code == 400
    assert c.post("/api/users/register", json={"email": "x@example.com", "password": "short"}).status_code == 400
    assert c.post("/api/users/register", json={"email": "x@example.com", "password": "p" * 200}).status_code == 400
    # Nobody can sign up as the owner to get admin rights.
    assert c.post("/api/users/register", json={"email": "Owner@Example.com", "password": "longenough"}).status_code == 403
    assert c.post("/api/users/register", json={"email": "ok@example.com", "password": "longenough"}).status_code == 201
    for i in range(10):
        c.post("/api/users/register", json={"email": f"u{i}@example.com", "password": "longenough"})
    assert c.post("/api/users/register", json={"email": "late@example.com", "password": "longenough"}).status_code == 429


def test_credits_cannot_go_negative():
    app, Session = make_app(watch_access.router)
    c = TestClient(app)
    uid, auth = signed_in(Session, "free")
    key = c.post("/api/watch/account/keys", json={}, headers=auth).json()["key"]
    s = Session()
    watch_access.wallet(uid, s).balance = 3
    s.commit()
    spent = 0
    for _ in range(5):
        try:
            watch_access.charge_key(key, 1, s)
            spent += 1
        except Exception:  # noqa: BLE001
            pass
    assert spent == 3 and watch_access.wallet(uid, s).balance == 0


def test_training_data_is_owner_only(monkeypatch):
    from lyra.authenticator.api import router as auth_router
    app, Session = make_app(auth_router)
    monkeypatch.setenv("LYRA_ADMIN_EMAILS", "owner@example.com")
    assert TestClient(app).get("/api/auth/training/export").status_code == 401
    _, customer = signed_in(Session, email="customer@example.com")
    assert TestClient(app).get("/api/auth/training/export", headers=customer).status_code == 403
    _, owner = signed_in(Session, email="owner@example.com")
    assert TestClient(app).get("/api/auth/training/export", headers=owner).status_code == 200


def test_sites_cant_be_registered_without_an_account():
    from lyra.authenticator.api import router as auth_router
    app, _ = make_app(auth_router)
    r = TestClient(app).post("/api/auth/register", json={"domain": "spam.example", "email": "x@spam.example"})
    assert r.status_code == 410
