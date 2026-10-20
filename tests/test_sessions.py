"""Sign-in (lyra/api/sessions.py, lyra/api/users_api.py): server-side sessions in an HttpOnly
cookie, no token for page scripts to keep, cross-site requests refused, sessions that can be
ended, password changes that sign out other browsers, and passwords that aren't guessable."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-sess-test-"))
os.environ["LYRA_INSECURE_COOKIES"] = "1"

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import ratelimit, sessions, users_api  # noqa: E402
from lyra.db.models import LoginSession  # noqa: E402
from _watchdb import make_app  # noqa: E402

SITE = "http://testserver"
PASSWORD = "plum kettle orbit 7"


@pytest.fixture
def app():
    ratelimit.reset()
    app, Session = make_app(users_api.router)
    app.state.Session = Session
    return app


def _browser(app):
    return TestClient(app, headers={"Origin": SITE})


def _signed_up(app, email="ada@example.com"):
    c = _browser(app)
    r = c.post("/api/users/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return c


def test_sign_in_gives_a_cookie_and_no_token(app):
    c = _signed_up(app)
    c.cookies.clear()
    r = c.post("/api/users/login", json={"email": "ada@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert "token" not in r.json()
    cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith("lyra_session="))
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert c.get("/api/users/me").json()["email"] == "ada@example.com"


def test_only_a_hash_of_the_session_is_stored(app):
    c = _signed_up(app)
    token = c.cookies.get(sessions.COOKIE)
    s = app.state.Session()
    stored = [r.token_hash for r in s.query(LoginSession).all()]
    s.close()
    assert token not in stored and len(stored) == 1


def test_wrong_email_and_wrong_password_look_the_same(app):
    _signed_up(app)
    c = _browser(app)
    a = c.post("/api/users/login", json={"email": "ada@example.com", "password": "nope nope nope"})
    b = c.post("/api/users/login", json={"email": "nobody@example.com", "password": "nope nope nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


@pytest.mark.parametrize("password", ["short1", "password123", "aaaaaaaaaaaa", "lovelace@example.com", "lovelace-rules-99",
                                      "x" * 73])
def test_guessable_passwords_are_refused(app, password):
    r = _browser(app).post("/api/users/register", json={"email": "lovelace@example.com", "password": password})
    assert r.status_code == 400


def test_old_page_tokens_no_longer_work_except_to_move_once(app):
    c = _signed_up(app)
    uid = c.get("/api/users/me").json()["id"]
    old = jwt.encode({"sub": str(uid), "exp": datetime.now(timezone.utc) + timedelta(days=3)},
                     users_api.SECRET_KEY, algorithm="HS256")
    fresh = _browser(app)
    assert fresh.get("/api/users/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    # from another site: refused
    evil = TestClient(app, headers={"Origin": "https://evil.example"})
    assert evil.post("/api/users/session", headers={"Authorization": f"Bearer {old}"}).status_code == 403
    r = fresh.post("/api/users/session", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 200
    assert fresh.get("/api/users/me").status_code == 200


def test_requests_from_other_sites_are_refused(app):
    c = _signed_up(app)
    cookie = c.cookies.get(sessions.COOKIE)
    evil = TestClient(app, headers={"Origin": "https://evil.example"})
    evil.cookies.set(sessions.COOKIE, cookie)
    assert evil.put("/api/users/me", json={"name": "pwned"}).status_code == 403
    assert evil.post("/api/users/sessions/end-others").status_code == 403
    sneaky = TestClient(app, headers={"Sec-Fetch-Site": "cross-site"})
    sneaky.cookies.set(sessions.COOKIE, cookie)
    assert sneaky.put("/api/users/me", json={"name": "pwned"}).status_code == 403
    # reading is fine, and the real site can change things
    assert evil.get("/api/users/me").status_code == 200
    assert c.put("/api/users/me", json={"name": "Ada"}).json()["name"] == "Ada"


def test_sign_out_ends_the_session_on_the_server(app):
    c = _signed_up(app)
    cookie = c.cookies.get(sessions.COOKIE)
    c.post("/api/users/logout")
    replay = _browser(app)
    replay.cookies.set(sessions.COOKIE, cookie)
    assert replay.get("/api/users/me").status_code == 401


def test_signing_in_replaces_a_planted_session_id(app):
    _signed_up(app)
    c = _browser(app)
    r = c.post("/api/users/login", json={"email": "ada@example.com", "password": PASSWORD},
               headers={"Cookie": f"{sessions.COOKIE}=planted-by-someone-else"})
    given = next(h for h in r.headers.get_list("set-cookie") if h.startswith(sessions.COOKIE + "="))
    assert "planted-by-someone-else" not in given


def test_sessions_expire_when_idle_or_too_old(app):
    c = _signed_up(app)
    s = app.state.Session()
    row = s.query(LoginSession).one()
    row.last_seen = datetime.now(timezone.utc) - sessions.IDLE - timedelta(minutes=1)
    s.commit()
    s.close()
    assert c.get("/api/users/me").status_code == 401

    c = _signed_up(app, "bo@example.com")
    s = app.state.Session()
    row = s.query(LoginSession).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    s.commit()
    s.close()
    assert c.get("/api/users/me").status_code == 401


def test_see_and_end_other_browsers(app):
    laptop = _signed_up(app)
    phone = _browser(app)
    phone.post("/api/users/login", json={"email": "ada@example.com", "password": PASSWORD})
    rows = laptop.get("/api/users/sessions").json()
    assert len(rows) == 2 and sum(r["current"] for r in rows) == 1
    other = next(r for r in rows if not r["current"])
    # someone else's account can't end it
    assert _signed_up(app, "bo@example.com").delete(f"/api/users/sessions/{other['id']}").status_code == 404
    assert phone.get("/api/users/me").status_code == 200
    assert laptop.post("/api/users/sessions/end-others").json()["ended"] == 1
    assert phone.get("/api/users/me").status_code == 401
    assert laptop.get("/api/users/me").status_code == 200


def test_changing_password_needs_the_old_one_and_signs_out_elsewhere(app):
    laptop = _signed_up(app)
    phone = _browser(app)
    phone.post("/api/users/login", json={"email": "ada@example.com", "password": PASSWORD})
    assert laptop.post("/api/users/password", json={"current_password": "wrong one here",
                                                    "new_password": "violet harbour 42"}).status_code == 400
    assert laptop.post("/api/users/password", json={"current_password": PASSWORD,
                                                    "new_password": "password123"}).status_code == 400
    r = laptop.post("/api/users/password", json={"current_password": PASSWORD, "new_password": "violet harbour 42"})
    assert r.json() == {"ok": True, "signed_out_elsewhere": 1}
    assert phone.get("/api/users/me").status_code == 401
    assert laptop.get("/api/users/me").status_code == 200
    fresh = _browser(app)
    assert fresh.post("/api/users/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code == 401
    assert fresh.post("/api/users/login", json={"email": "ada@example.com", "password": "violet harbour 42"}).status_code == 200
