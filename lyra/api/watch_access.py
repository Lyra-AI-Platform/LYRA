"""Who gets how much of Lyra Watch, and how they pay.

  * public       anyone: the free tier (live preview an hour behind, top of the leaderboards,
                 summaries). Enough to see what's there.
  * subscriber   a signed-in user with Lyra Watch Pro (its own Stripe subscription) or any paid
                 Lyra plan: everything, real time, in the browser.
  * key          an API key (header `X-Lyra-Key: lw_...` or `Authorization: Bearer lw_...`):
                 everything, real time, for AI agents and scripts. Each request spends credits
                 from the owner's prepaid wallet; at zero the API answers 402 with how to top up.

Payments go through Stripe Checkout with inline prices, so nothing has to be set up in the
Stripe dashboard beyond the secret key the main plans already use.
"""
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.api import entitlements
from lyra.api.users_api import get_current_user
from lyra.db.database import get_db
from lyra.db.models import ApiKey, CreditPurchase, CreditWallet, User, WatchSubscription, _api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watch/account", tags=["watch-account"])

APP_URL = os.getenv("APP_URL", "https://lyraauth.com")
CURRENCY = os.getenv("LYRA_WATCH_CURRENCY", "usd")
PRO_CENTS = int(os.getenv("LYRA_WATCH_PRO_CENTS", 700))              # Lyra Watch Pro, per month
# pack -> (price in cents, credits)
CREDIT_PACKS: Dict[str, tuple] = {"starter": (500, 1_000), "builder": (2_000, 5_000), "scale": (8_000, 25_000)}
FREE_CREDITS = int(os.getenv("LYRA_WATCH_FREE_CREDITS", 100))       # once, with a user's first key
COSTS = {"person": 1, "people": 2, "feed": 2, "impact": 5, "live": 10}
MAX_KEYS = 10
# Stripe's tax code for software/data delivered online, needed by Managed Payments.
TAX_CODE = os.getenv("LYRA_STRIPE_TAX_CODE", "txcd_10000000")


def pricing() -> Dict:
    """Machine-readable prices, for people and for AI agents deciding whether to pay."""
    return {
        "currency": CURRENCY,
        "free": {"price": 0, "includes": ["live preview one hour behind", "top 5 of Who moves markets",
                                           "people directory and summaries", "JSON feed one hour behind"]},
        "watch_pro": {"price_cents": PRO_CENTS, "interval": "month",
                      "includes": ["real-time live stream", "full Who moves markets record", "every person's market impact",
                                   "said & traded", "ad-free"],
                      "subscribe": f"{APP_URL}/watch/account/"},
        "api_credits": {"packs": {k: {"price_cents": c, "credits": n} for k, (c, n) in CREDIT_PACKS.items()},
                        "cost_per_request": COSTS, "free_credits_with_first_key": FREE_CREDITS,
                        "how": "Send your key as the X-Lyra-Key header. Each response has X-Lyra-Credits-Remaining.",
                        "buy": f"{APP_URL}/watch/account/"},
    }


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def has_watch(user: Optional[User], db: Session) -> bool:
    if not user:
        return False
    if entitlements.is_paid(user):
        return True
    sub = db.query(WatchSubscription).filter(WatchSubscription.user_id == user.id).first()
    return bool(sub and sub.status in ("active", "trialing"))


def wallet(user_id: int, db: Session) -> CreditWallet:
    w = db.query(CreditWallet).filter(CreditWallet.user_id == user_id).first()
    if not w:
        w = CreditWallet(user_id=user_id, balance=0, spent=0)
        db.add(w)
        db.commit()
        db.refresh(w)
    return w


@dataclass
class Viewer:
    kind: str                      # public | subscriber | key
    user: Optional[User] = None
    credits_left: Optional[int] = None

    @property
    def full(self) -> bool:
        return self.kind in ("subscriber", "key")


def _out_of_credits(balance: int, cost: int) -> HTTPException:
    return HTTPException(402, {"error": "payment_required", "reason": "out_of_credits",
                               "message": f"This request costs {cost} credit{'s' if cost != 1 else ''}; the key's wallet has {balance}. "
                                          "Buy credits to continue.",
                               "pricing": pricing(), "upgrade_url": f"{APP_URL}/watch/account/"})


def charge_key(key: str, cost: int, db: Session) -> Viewer:
    row = db.query(ApiKey).filter(ApiKey.key_hash == _hash(key), ApiKey.is_active == True).first()  # noqa: E712
    if not row:
        raise HTTPException(401, {"error": "invalid_key", "message": "Unknown or revoked API key.",
                                  "get_a_key": f"{APP_URL}/watch/account/"})
    w = wallet(row.user_id, db)
    if w.balance < cost:
        raise _out_of_credits(w.balance, cost)
    w.balance -= cost
    w.spent += cost
    row.requests += 1
    row.last_used = datetime.now(timezone.utc)
    db.commit()
    return Viewer("key", db.get(User, row.user_id), w.balance)


def identify(cost_name: str):
    """FastAPI dependency: who is asking. API keys are charged here; everyone else is free."""
    cost = COSTS[cost_name]

    def dep(response: Response, db: Session = Depends(get_db), authorization: str = Header(""),
            x_lyra_key: str = Header("")) -> Viewer:
        bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        key = x_lyra_key.strip() or (bearer if bearer.startswith("lw_") else "")
        if key:
            v = charge_key(key, cost, db)
            response.headers["X-Lyra-Credits-Remaining"] = str(v.credits_left)
            response.headers["X-Lyra-Credits-Charged"] = str(cost)
            return v
        user = entitlements.user_from_token(bearer, db) if bearer else None
        if has_watch(user, db):
            return Viewer("subscriber", user)
        return Viewer("public", user)
    return dep


def require_watch(cost_name: str = "live"):
    """FastAPI dependency for subscriber features: Watch Pro (or a paid plan), or an API key
    with credits; otherwise 402 with the prices."""
    inner = identify(cost_name)

    def dep(viewer: Viewer = Depends(inner)) -> Viewer:
        if not viewer.full:
            raise HTTPException(402, {"error": "payment_required", "feature": "watch_live", "reason": "subscribers_only",
                                      "message": "Lyra Watch Live in real time is for Lyra Watch Pro subscribers.",
                                      "upgrade_url": "/watch/account/", "pricing": pricing()})
        return viewer
    return dep


# ── Account routes ─────────────────────────────────────────────────────────

@router.get("/pricing")
def get_pricing():
    return pricing()


@router.get("")
def account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.query(WatchSubscription).filter(WatchSubscription.user_id == user.id).first()
    w = wallet(user.id, db)
    keys = db.query(ApiKey).filter(ApiKey.user_id == user.id, ApiKey.is_active == True).all()  # noqa: E712
    return {"watch_pro": has_watch(user, db), "via_main_plan": entitlements.is_paid(user),
            "subscription_status": sub.status if sub else None,
            "credits": {"balance": w.balance, "spent": w.spent},
            "keys": [{"id": k.id, "name": k.name, "prefix": k.prefix, "requests": k.requests,
                      "created_at": k.created_at.isoformat() if k.created_at else None,
                      "last_used": k.last_used.isoformat() if k.last_used else None} for k in keys],
            "pricing": pricing()}


class KeyRequest(BaseModel):
    name: str = ""


@router.post("/keys")
def create_key(req: KeyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A new API key, shown once. A user's very first key comes with FREE_CREDITS."""
    if db.query(ApiKey).filter(ApiKey.user_id == user.id, ApiKey.is_active == True).count() >= MAX_KEYS:  # noqa: E712
        raise HTTPException(400, f"At most {MAX_KEYS} keys; revoke one first.")
    first = db.query(ApiKey).filter(ApiKey.user_id == user.id).count() == 0
    key = _api_key()
    db.add(ApiKey(user_id=user.id, name=req.name[:60], prefix=key[:10], key_hash=_hash(key)))
    w = wallet(user.id, db)
    if first:
        w.balance += FREE_CREDITS
    db.commit()
    return {"key": key, "note": "Copy it now: it won't be shown again.", "credits": w.balance,
            "free_credits_added": FREE_CREDITS if first else 0}


@router.delete("/keys/{key_id}")
def revoke_key(key_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "No such key")
    row.is_active = False
    db.commit()
    return {"revoked": key_id}


def _stripe():
    from lyra.api.billing_api import STRIPE_SECRET_KEY, _stripe as s
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Payments aren't switched on yet.")
    return s()


def _customer(user: User, db: Session, stripe) -> str:
    if not user.stripe_customer_id:
        user.stripe_customer_id = stripe.Customer.create(email=user.email, metadata={"lyra_user_id": str(user.id)}).id
        db.commit()
    return user.stripe_customer_id


def _checkout(stripe, **kw):
    from lyra.api.billing_api import MANAGED_PAYMENTS
    return stripe.checkout.Session.create(
        **kw, **({"managed_payments": {"enabled": True}} if MANAGED_PAYMENTS else {}),
        allow_promotion_codes=True)


@router.post("/checkout/pro")
def checkout_pro(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lyra Watch Pro: its own monthly subscription, separate from the main plans."""
    if has_watch(user, db):
        raise HTTPException(400, "You already have Lyra Watch Pro.")
    stripe = _stripe()
    meta = {"lyra_user_id": str(user.id), "product": "watch"}
    session = _checkout(
        stripe, customer=_customer(user, db, stripe), mode="subscription", client_reference_id=str(user.id),
        line_items=[{"quantity": 1, "price_data": {
            "currency": CURRENCY, "unit_amount": PRO_CENTS, "recurring": {"interval": "month"},
            "product_data": {"name": "Lyra Watch Pro", "tax_code": TAX_CODE,
                             "description": "Real-time Lyra Watch: live stream, market impact, said & traded."}}}],
        subscription_data={"metadata": meta}, metadata=meta,
        success_url=f"{APP_URL}/watch/account/?pro=1", cancel_url=f"{APP_URL}/watch/account/?cancelled=1")
    return {"checkout_url": session.url}


class CreditsRequest(BaseModel):
    pack: str = "starter"


@router.post("/checkout/credits")
def checkout_credits(req: CreditsRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A one-off credit pack for API keys."""
    if req.pack not in CREDIT_PACKS:
        raise HTTPException(400, f"Pack must be one of {', '.join(CREDIT_PACKS)}")
    cents, credits = CREDIT_PACKS[req.pack]
    stripe = _stripe()
    session = _checkout(
        stripe, customer=_customer(user, db, stripe), mode="payment", client_reference_id=str(user.id),
        line_items=[{"quantity": 1, "price_data": {
            "currency": CURRENCY, "unit_amount": cents,
            "product_data": {"name": f"Lyra Watch API credits ({credits:,})", "tax_code": TAX_CODE}}}],
        metadata={"lyra_user_id": str(user.id), "product": "credits", "credits": str(credits)},
        success_url=f"{APP_URL}/watch/account/?credits=1", cancel_url=f"{APP_URL}/watch/account/?cancelled=1")
    return {"checkout_url": session.url}


# ── Stripe webhook (called from billing_api's webhook) ─────────────────────

def handle_webhook(et: str, data: Dict, db: Session, stripe=None) -> bool:
    """Handles Lyra Watch's own payments. Returns True when the event was one of them, so the
    main-plan handler leaves it alone (a Watch Pro subscription must never change user.tier)."""
    meta = data.get("metadata") or {}
    product = meta.get("product")
    if et == "checkout.session.completed" and product == "credits":
        if data.get("payment_status") == "paid" and not db.query(CreditPurchase).filter(
                CreditPurchase.stripe_session_id == data["id"]).first():
            uid, credits = int(meta["lyra_user_id"]), int(meta["credits"])
            db.add(CreditPurchase(user_id=uid, stripe_session_id=data["id"], credits=credits,
                                  amount_cents=int(data.get("amount_total") or 0)))
            wallet(uid, db).balance += credits
            db.commit()
            logger.info(f"User {uid} bought {credits} Watch API credits")
        return True
    if et == "checkout.session.completed" and product == "sponsor":
        from lyra.api import ads_api
        ads_api.mark_paid(int(meta["sponsor_id"]), data, db)
        return True
    if et == "checkout.session.completed" and product == "watch":
        if data.get("subscription") and stripe is not None:
            sub = stripe.Subscription.retrieve(data["subscription"])
            sub = sub.to_dict() if hasattr(sub, "to_dict") else sub
            _set_subscription(sub, db)
        return True
    if et.startswith("customer.subscription.") and product == "watch":
        _set_subscription(data, db, deleted=et.endswith(".deleted"))
        return True
    return False


def _set_subscription(sub: Dict, db: Session, deleted: bool = False):
    uid = int((sub.get("metadata") or {})["lyra_user_id"])
    row = db.query(WatchSubscription).filter(WatchSubscription.user_id == uid).first()
    if not row:
        row = WatchSubscription(user_id=uid)
        db.add(row)
    row.stripe_subscription_id = sub.get("id")
    row.status = "canceled" if deleted else sub.get("status", "inactive")
    db.commit()
    logger.info(f"User {uid} Lyra Watch Pro → {row.status}")
