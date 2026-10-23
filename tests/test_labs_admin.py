"""Lyra Labs (connections, model calls, safety, endpoint checks) and the owner's admin access."""
import os
import tempfile

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-labs-test-"))
os.environ["LYRA_INSECURE_COOKIES"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import admin_api, entitlements, labs_api, ratelimit, users_api  # noqa: E402
from lyra.db.models import LabsConnection  # noqa: E402
from lyra.labs import llm  # noqa: E402
from _watchdb import make_app, signed_in  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    ratelimit.reset()
    monkeypatch.setenv("LYRA_ADMIN_EMAILS", "owner@example.com")
    app, Session = make_app(users_api.router, labs_api.router, admin_api.router)
    app.state.Session = Session
    return app


def _c(app):
    return TestClient(app, headers={"Origin": "http://testserver"})


def test_keys_are_encrypted_and_never_returned(app):
    _, h = signed_in(app.state.Session, "free")
    c = _c(app)
    r = c.post("/api/labs/connections", json={"kind": "anthropic", "key": "sk-ant-secret-12345678", "name": "Claude"}, headers=h)
    assert r.status_code == 201 and r.json()["key"] == "…5678"
    s = app.state.Session()
    row = s.query(LabsConnection).one()
    assert "secret" not in row.key_sealed and llm.unseal(row.key_sealed) == "sk-ant-secret-12345678"
    s.close()
    assert "secret" not in c.get("/api/labs/connections", headers=h).text


@pytest.mark.parametrize("url", ["http://api.example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1",
                                 "https://10.0.0.5/v1", "https://169.254.169.254/latest", "https://user:pw@api.openai.com/v1"])
def test_private_or_insecure_endpoints_are_refused(app, url):
    _, h = signed_in(app.state.Session, "free")
    r = _c(app).post("/api/labs/connections", json={"kind": "openai", "base_url": url, "key": "k" * 20}, headers=h)
    assert r.status_code == 400


def test_every_call_carries_the_safety_rules(app, monkeypatch):
    seen = {}

    async def fake(conn, system, messages, max_tokens=1500):
        seen["system"] = system
        return "ok"
    monkeypatch.setattr(llm, "complete", fake)
    _, h = signed_in(app.state.Session, "starter")
    r = _c(app).post("/api/labs/complete", json={"engine": "lyra", "system": "Be brief.", "messages": [{"role": "user", "content": "hi"}]}, headers=h)
    assert r.status_code == 200 and r.json()["text"] == "ok"
    assert seen["system"].startswith(labs_api.SAFETY) and seen["system"].endswith("Be brief.")


def test_lyras_model_is_for_members_and_other_peoples_ai_is_off_limits(app, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: None)
    s = app.state.Session()
    from lyra.db.models import User
    from datetime import datetime, timedelta, timezone
    _, h = signed_in(app.state.Session, "free")
    u = s.query(User).filter(User.tier == "free").first()
    u.created_at = datetime.now(timezone.utc) - timedelta(days=60)   # trial over
    s.commit()
    s.close()
    c = _c(app)
    assert c.post("/api/labs/complete", json={"engine": "lyra", "messages": [{"role": "user", "content": "hi"}]}, headers=h).status_code == 402
    _, other = signed_in(app.state.Session, "free")
    cid = c.post("/api/labs/connections", json={"kind": "anthropic", "key": "sk-ant-other-12345678"}, headers=other).json()["id"]
    assert c.post("/api/labs/complete", json={"engine": cid, "messages": [{"role": "user", "content": "hi"}]}, headers=h).status_code == 404


def test_owner_gets_everything_and_the_admin_page_hides_from_others(app):
    _, owner = signed_in(app.state.Session, "free", email="owner@example.com")
    _, someone = signed_in(app.state.Session, "free")
    c = _c(app)
    assert c.get("/api/admin/overview", headers=someone).status_code == 404
    o = c.get("/api/admin/overview", headers=owner).json()
    assert o["accounts"]["total"] == 2 and "newswire" in o
    s = app.state.Session()
    from lyra.db.models import User
    u = s.query(User).filter(User.email == "owner@example.com").one()
    assert entitlements.is_paid(u) and entitlements.is_admin(u)
    s.close()
