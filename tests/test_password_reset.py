"""Forgotten passwords: the same answer for any email, and links that work once."""
import os
import tempfile

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-reset-test-"))
os.environ["LYRA_INSECURE_COOKIES"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import ratelimit, users_api  # noqa: E402
from _watchdb import make_app  # noqa: E402

OLD, NEW = "plum kettle orbit 7", "harbour violet stone 9"
EMAIL = "reader@example.com"


@pytest.fixture
def client(monkeypatch):
    ratelimit.reset()
    app, _ = make_app(users_api.router)
    sent = []
    monkeypatch.setattr(users_api, "_send_reset", lambda email, token: sent.append(token))
    monkeypatch.setattr(users_api, "_send_changed", lambda email: None)
    c = TestClient(app)
    assert c.post("/api/users/register", json={"email": EMAIL, "password": OLD, "name": "R"}).status_code == 201
    c.cookies.clear()
    c.sent = sent
    return c


def test_unknown_email_gets_the_same_answer(client):
    assert client.post("/api/users/password/forgot", json={"email": "nobody@example.com"}).json() == {"ok": True}
    assert client.sent == []


def test_reset_works_once(client):
    client.post("/api/users/password/forgot", json={"email": EMAIL})
    token = client.sent[0]
    assert client.post("/api/users/password/reset", json={"token": token, "new_password": NEW}).status_code == 200
    assert client.post("/api/users/login", json={"email": EMAIL, "password": NEW}).status_code == 200
    assert client.post("/api/users/password/reset", json={"token": token, "new_password": OLD}).status_code == 400


def test_a_newer_link_cancels_the_older_one(client):
    client.post("/api/users/password/forgot", json={"email": EMAIL})
    client.post("/api/users/password/forgot", json={"email": EMAIL})
    assert client.post("/api/users/password/reset", json={"token": client.sent[0], "new_password": NEW}).status_code == 400
    assert client.post("/api/users/password/reset", json={"token": client.sent[1], "new_password": NEW}).status_code == 200
