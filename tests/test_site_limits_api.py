"""Sites API and siteverify: plan limits on every plan, hashed keys, a real hostname and score."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-sites-test-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import sites_api  # noqa: E402
from lyra.authenticator import api as auth_api  # noqa: E402
from lyra.authenticator.guard import hash_secret  # noqa: E402
from lyra.db.models import Site, UsageRecord, User, VerifiedToken  # noqa: E402
from _watchdb import make_app, signed_in  # noqa: E402


@pytest.fixture
def world():
    app, Session = make_app(sites_api.router, auth_api.router)
    return TestClient(app), Session




def test_a_new_key_is_shown_once_and_stored_hashed(world):
    c, Session = world
    _, h = signed_in(Session, tier="starter")
    made = c.post("/api/sites", json={"name": "a"}, headers=h).json()
    assert made["secret_key"].startswith("lyra_secret_")
    assert c.get("/api/sites", headers=h).json()[0]["secret_key"] is None
    s = Session()
    assert s.query(Site).first().secret_key == hash_secret(made["secret_key"])


def test_starter_stops_at_ten_sites(world):
    c, Session = world
    _, h = signed_in(Session, tier="starter")
    for i in range(10):
        assert c.post("/api/sites", json={"name": str(i)}, headers=h).status_code == 201
    r = c.post("/api/sites", json={"name": "11"}, headers=h)
    assert r.status_code == 402 and "10 sites" in r.json()["detail"]["message"]


def test_pro_has_no_site_cap(world):
    c, Session = world
    _, h = signed_in(Session, tier="pro")
    for i in range(12):
        assert c.post("/api/sites", json={"name": str(i)}, headers=h).status_code == 201


def _token(Session, site_id, **kw):
    s = Session()
    s.add(VerifiedToken(token="t", site_id=site_id, expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), **kw))
    s.commit()


def test_siteverify_reports_where_it_was_solved_and_the_real_score(world):
    c, Session = world
    _, h = signed_in(Session, tier="starter")
    made = c.post("/api/sites", json={"name": "a", "domain": "example.com"}, headers=h).json()
    _token(Session, made["id"], hostname="shop.example.com", score=0.95)
    out = c.post("/api/auth/siteverify", json={"secret_key": made["secret_key"], "token": "t"}).json()
    assert out["success"] and out["hostname"] == "shop.example.com" and out["score"] == 0.95


def test_siteverify_rejects_a_wrong_key(world):
    c, Session = world
    _, h = signed_in(Session, tier="starter")
    made = c.post("/api/sites", json={"name": "a"}, headers=h).json()
    _token(Session, made["id"])
    out = c.post("/api/auth/siteverify", json={"secret_key": "lyra_secret_wrong", "token": "t"}).json()
    assert out["error-codes"] == ["invalid-secret-key"]


def test_a_paid_plan_stops_at_its_monthly_allowance(world):
    c, Session = world
    _, h = signed_in(Session, tier="starter")
    made = c.post("/api/sites", json={"name": "a"}, headers=h).json()
    s = Session()
    s.add(UsageRecord(site_id=made["id"], date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), count=100_000))
    s.commit()
    _token(Session, made["id"])
    assert c.post("/api/auth/siteverify", json={"secret_key": made["secret_key"], "token": "t"}).status_code == 402
    assert c.get(f"/api/sites/{made['id']}/usage", headers=h).json()["remaining"] == 0
