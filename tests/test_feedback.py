"""Feedback (lyra/api/feedback_api.py): kept even without email, bots dropped, owner-only reading."""
import os
import tempfile
import time

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-fb-test-"))
os.environ["LYRA_INSECURE_COOKIES"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import feedback_api, ratelimit, users_api  # noqa: E402
from lyra.db.models import Feedback  # noqa: E402
from _watchdb import make_app  # noqa: E402

PASSWORD = "plum kettle orbit 7"


@pytest.fixture
def app(monkeypatch):
    ratelimit.reset()
    app, Session = make_app(users_api.router, feedback_api.router)
    sent = []
    monkeypatch.setattr(feedback_api, "SessionLocal", Session)
    monkeypatch.setattr(feedback_api, "send_email", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setenv("LYRA_ADMIN_EMAILS", "owner@example.com")
    monkeypatch.setenv("LYRA_ALLOW_ADMIN_SIGNUP", "1")
    app.state.Session, app.state.sent = Session, sent
    return app


def _c(app):
    return TestClient(app, headers={"Origin": "http://testserver"})


def _msg(**over):
    return {"kind": "idea", "message": "Please add dark mode", "email": "ada@example.com", "rating": 4,
            "started_at": int(time.time() * 1000) - 10_000, **over}


def test_feedback_is_stored_and_emailed(app):
    r = _c(app).post("/api/feedback", json=_msg())
    assert r.status_code == 201 and r.json()["reference"].startswith("LF-")
    s = app.state.Session()
    f = s.query(Feedback).one()
    assert f.message == "Please add dark mode" and f.emailed
    s.close()
    to, subject, text, reply = app.state.sent[0]
    assert to == "owner@example.com" and "dark mode" in text and reply == "ada@example.com"


def test_bots_are_thanked_but_nothing_is_kept(app):
    for bad in (_msg(website="http://spam"), _msg(started_at=int(time.time() * 1000))):
        assert _c(app).post("/api/feedback", json=bad).status_code == 201
    s = app.state.Session()
    assert s.query(Feedback).count() == 0
    s.close()


def test_cross_site_posts_and_junk_are_refused(app):
    assert TestClient(app, headers={"Origin": "https://evil.example"}).post("/api/feedback", json=_msg()).status_code == 403
    assert _c(app).post("/api/feedback", json=_msg(message="")).status_code == 400
    assert _c(app).post("/api/feedback", json=_msg(email="not-an-email")).status_code == 400


def test_only_the_owner_reads_feedback(app):
    _c(app).post("/api/feedback", json=_msg())
    someone = _c(app)
    someone.post("/api/users/register", json={"email": "ada@example.com", "password": PASSWORD})
    assert someone.get("/api/feedback").status_code == 404
    owner = _c(app)
    owner.post("/api/users/register", json={"email": "owner@example.com", "password": PASSWORD})
    assert owner.get("/api/feedback").json()[0]["message"] == "Please add dark mode"
