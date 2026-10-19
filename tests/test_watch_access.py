"""Lyra Watch paid access: the free tier, Watch Pro, API keys spending credits, Stripe webhooks
and sponsor slots. Stripe itself is never called."""
import os
import tempfile
from datetime import timedelta

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-access-test-"))

from fastapi.testclient import TestClient  # noqa: E402

from lyra.api import ads_api, watch_access, watch_api  # noqa: E402
from lyra.db.models import CreditWallet, Sponsor, User, WatchSubscription  # noqa: E402
from lyra.watch import service  # noqa: E402
from _watchdb import make_app, signed_in  # noqa: E402

IMPACT = {"days": 9, "big_moves": 4, "big_share": 0.44, "usual_big_share": 0.05, "lift": 8.8, "avg_abs_z": 1.9,
          "verdict": "strong", "first_day": "2026-09-20", "by_ticker": [{"ticker": "TSLA", "name": "Tesla", "days": 9}],
          "biggest": [{"date": "2026-10-09", "ticker": "TSLA", "move": -0.1, "z": -4}]}


def _people(n=8):
    service.save_people({"built_at": 1.0, "people": [
        {"name": f"Person {i}", "id": f"person-{i}", "slug": "", "watched": True, "job": "CEO", "mentions": 5,
         "companies": [{"name": "Tesla", "ticker": "TSLA"}], "tone": {"avg": 0, "label": "neutral"},
         "market_impact": {**IMPACT, "lift": 9 - i}, "said_and_traded": [{"ticker": "TSLA", "date": "2026-10-01"}]}
        for i in range(n)]})


def _app():
    app, Session = make_app(watch_api.router, watch_access.router, ads_api.router)
    return TestClient(app), Session


def test_free_tier_is_a_teaser():
    _people()
    c, _ = _app()
    body = c.get("/api/watch/impact").json()
    assert len(body["people"]) == watch_api.FREE_LEADERS and body["locked"] == 3 and body["pricing"]["watch_pro"]
    rec = c.get("/api/watch/people/person-0").json()
    assert "said_and_traded" not in rec and "biggest" not in rec["market_impact"]
    assert rec["market_impact"]["verdict"] == "strong" and rec["locked"]["said_and_traded_rows"] == 1


def test_watch_pro_and_paid_plans_see_everything():
    _people()
    c, Session = _app()
    uid, pro = signed_in(Session, "free")
    s = Session()
    s.add(WatchSubscription(user_id=uid, status="active"))
    s.commit()
    assert len(c.get("/api/watch/impact", headers=pro).json()["people"]) == 8
    r = c.get("/api/watch/people/person-0", headers=pro)
    assert r.json()["said_and_traded"] and r.headers["cache-control"] == "private, no-store"
    _, starter = signed_in(Session, "starter")
    assert c.get("/api/watch/impact", headers=starter).json()["locked"] == 0
    _, free = signed_in(Session, "free")
    assert c.get("/api/watch/impact", headers=free).json()["locked"] == 3


def test_api_keys_spend_credits_then_402():
    _people()
    c, Session = _app()
    uid, auth = signed_in(Session, "free")
    made = c.post("/api/watch/account/keys", json={"name": "my agent"}, headers=auth).json()
    assert made["key"].startswith("lw_") and made["credits"] == watch_access.FREE_CREDITS
    key = {"X-Lyra-Key": made["key"]}
    r = c.get("/api/watch/impact", headers=key)
    assert len(r.json()["people"]) == 8
    assert r.headers["x-lyra-credits-remaining"] == str(watch_access.FREE_CREDITS - watch_access.COSTS["impact"])
    # The same key works as a bearer token.
    assert c.get("/api/watch/people/person-1", headers={"Authorization": f"Bearer {made['key']}"}).json()["said_and_traded"]
    s = Session()
    s.query(CreditWallet).filter(CreditWallet.user_id == uid).first().balance = 2
    s.commit()
    r = c.get("/api/watch/impact", headers=key)
    assert r.status_code == 402 and r.json()["detail"]["reason"] == "out_of_credits"
    assert r.json()["detail"]["pricing"]["api_credits"]["packs"]
    # A second key brings no more free credits; a revoked key stops working.
    second = c.post("/api/watch/account/keys", json={}, headers=auth).json()
    assert second["free_credits_added"] == 0
    kid = c.get("/api/watch/account", headers=auth).json()["keys"][0]["id"]
    c.delete(f"/api/watch/account/keys/{kid}", headers=auth)
    assert c.get("/api/watch/impact", headers=key).status_code == 401
    assert c.get("/api/watch/impact", headers={"X-Lyra-Key": "lw_nope"}).status_code == 401


def test_api_keys_never_get_x_posts():
    from lyra.watch import live
    import time
    live.hub.history.clear()
    live.hub.publish({"id": "x1", "ts": time.time(), "title": "a post", "x": True})
    live.hub.publish({"id": "n1", "ts": time.time(), "title": "news"})
    c, Session = _app()
    _, auth = signed_in(Session, "pro")
    key = {"X-Lyra-Key": c.post("/api/watch/account/keys", json={}, headers=auth).json()["key"]}
    assert [e["id"] for e in c.get("/api/watch/live/recent", headers=key).json()["events"]] == ["n1"]
    assert {e["id"] for e in c.get("/api/watch/live/recent", headers=auth).json()["events"]} == {"x1", "n1"}


def test_webhook_credits_are_added_once_and_watch_pro_never_touches_tier():
    _, Session = _app()
    uid, _ = signed_in(Session, "free")
    s = Session()
    paid = {"id": "cs_1", "payment_status": "paid", "amount_total": 500,
            "metadata": {"product": "credits", "credits": "1000", "lyra_user_id": str(uid)}}
    assert watch_access.handle_webhook("checkout.session.completed", paid, s)
    assert watch_access.handle_webhook("checkout.session.completed", paid, s)  # Stripe retries
    assert watch_access.wallet(uid, s).balance == 1000
    sub = {"id": "sub_1", "status": "active", "metadata": {"product": "watch", "lyra_user_id": str(uid)}}
    assert watch_access.handle_webhook("customer.subscription.updated", sub, s)
    user = s.get(User, uid)
    assert watch_access.has_watch(user, s) and user.tier == "free"
    assert watch_access.handle_webhook("customer.subscription.deleted", sub, s)
    assert not watch_access.has_watch(user, s)
    # Main-plan events are left to the main handler.
    assert not watch_access.handle_webhook("customer.subscription.updated", {"id": "sub_2", "metadata": {}}, s)


def test_sponsor_slot_lifecycle(monkeypatch):
    monkeypatch.setenv("LYRA_ADMIN_EMAILS", "owner@example.com")
    c, Session = _app()
    assert c.get("/api/ads/slot").json()["kind"] == "house"
    uid, auth = signed_in(Session, "free")
    assert c.post("/api/ads/book", json={"headline": "Hi", "url": "https://x.com"}, headers=auth).status_code == 400
    assert c.post("/api/ads/book", json={"headline": "Great tool", "url": "http://x.com"}, headers=auth).status_code == 400
    s = Session()
    sp = Sponsor(user_id=uid, headline="Great tool", url="https://example.org", weeks=2, status="unpaid")
    s.add(sp)
    s.commit()
    assert watch_access.handle_webhook("checkout.session.completed", {"id": "cs_9", "payment_status": "paid",
                                       "metadata": {"product": "sponsor", "sponsor_id": str(sp.id)}}, s)
    s.refresh(sp)
    assert sp.status == "paid" and c.get("/api/ads/slot").json()["kind"] == "house"  # not live until approved
    assert c.post(f"/api/ads/admin/{sp.id}/approve", headers=auth).status_code == 403
    _, owner = signed_in(Session, "free", email="owner@example.com")
    live_row = c.post(f"/api/ads/admin/{sp.id}/approve", headers=owner).json()
    assert live_row["status"] == "live"
    ad = c.get("/api/ads/slot").json()
    assert ad["kind"] == "sponsor" and ad["label"] == "Sponsored"
    r = c.get(ad["url"], follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://example.org"
    mine = c.get("/api/ads/mine", headers=auth).json()["slots"][0]
    assert mine["impressions"] == 1 and mine["clicks"] == 1
    # Subscribers see no ads.
    _, pro = signed_in(Session, "pro")
    assert c.get("/api/ads/slot", headers=pro).json()["kind"] == "none"
    s.refresh(sp)
    assert (sp.ends_at - sp.starts_at) == timedelta(weeks=2)


def test_pricing_is_public_and_machine_readable():
    c, _ = _app()
    p = c.get("/api/watch/account/pricing").json()
    assert p["watch_pro"]["price_cents"] > 0 and p["api_credits"]["cost_per_request"]["person"] == 1
