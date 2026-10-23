"""
Stripe billing API.

POST /api/billing/checkout       — create Stripe checkout session (upgrade to Pro)
POST /api/billing/portal         — create Stripe billing portal session
GET  /api/billing/status         — current subscription status
POST /api/billing/webhook        — Stripe webhook handler (no auth required)
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.db.database import get_db
from lyra.db.models import User
from lyra.api.users_api import get_current_user
from lyra.api import entitlements

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])

STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
APP_URL               = os.getenv("APP_URL", "https://lyraauth.com")
MANAGED_PAYMENTS      = os.getenv("STRIPE_MANAGED_PAYMENTS", "1") != "0"

# One Stripe Price per plan. STRIPE_<PLAN>_PRICE_ID wins when set; otherwise the price is found
# in Stripe by its lookup key (lyra_<plan>_monthly, already on the live Lyra prices), so the
# plans work as soon as STRIPE_SECRET_KEY is set and a price can be swapped in Stripe alone.
PLANS = ("starter", "pro", "business", "enterprise")
PRICE_IDS = {plan: os.getenv(f"STRIPE_{plan.upper()}_PRICE_ID", "") for plan in PLANS}
LOOKUP_KEYS = {plan: f"lyra_{plan}_monthly" for plan in PLANS}


def _resolve_prices() -> None:
    """Fill in any PRICE_IDS left empty from the Stripe lookup keys (once per process)."""
    missing = [p for p in PLANS if not PRICE_IDS[p]]
    if not missing or not STRIPE_SECRET_KEY:
        return
    try:
        found = _stripe().Price.list(lookup_keys=[LOOKUP_KEYS[p] for p in missing], active=True, limit=10)
    except Exception as e:  # noqa: BLE001 — Stripe down or key wrong: checkout reports it below
        logger.warning("Couldn't look up Stripe prices: %s", e)
        return
    by_key = {pr["lookup_key"]: pr["id"] for pr in found["data"]}
    for p in missing:
        PRICE_IDS[p] = by_key.get(LOOKUP_KEYS[p], "")

# Lazy-import stripe so the app starts even without it installed
def _stripe():
    try:
        import stripe as _s
        _s.api_key = STRIPE_SECRET_KEY
        return _s
    except ImportError:
        raise HTTPException(500, "Stripe not installed. Run: pip install stripe")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
def billing_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        **entitlements.status(user, db),
        "stripe_customer_id": user.stripe_customer_id,
        "has_subscription": bool(user.stripe_subscription_id),
        "payments_configured": bool(STRIPE_SECRET_KEY),
        "payments_mode": "live" if os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_", "rk_live_")) else "test",
    }


class CheckoutRequest(BaseModel):
    plan: str = "pro"   # starter | pro | business | enterprise

@router.post("/checkout")
def create_checkout(
    req: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe checkout session for the chosen plan."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe not configured. Set STRIPE_SECRET_KEY env var.")

    plan = req.plan.lower()
    if plan not in PLANS:
        raise HTTPException(400, "No such plan")
    _resolve_prices()
    price_id = PRICE_IDS.get(plan, "")
    if not price_id:
        raise HTTPException(503, f"No active Stripe price for the {plan} plan (lookup key {LOOKUP_KEYS[plan]}).")

    if user.stripe_subscription_id and entitlements.is_paid(user):
        # A second checkout would start a second subscription; plan changes go through the portal.
        raise HTTPException(409, "You already have a plan. Use Manage billing to switch plans.")

    stripe = _stripe()

    # Create or reuse Stripe customer
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"lyra_user_id": str(user.id)},
        )
        user.stripe_customer_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        # Stripe Managed Payments: Stripe (via its reseller) sells the subscription and handles
        # sales tax/VAT. Needs API version 2025-03-31.basil or later (stripe-python 16 uses 2026-09-30).
        # It rejects automatic_tax, tax_id_collection, payment_method_types and similar options,
        # so none are set here. Turn off with STRIPE_MANAGED_PAYMENTS=0.
        **({"managed_payments": {"enabled": True}} if MANAGED_PAYMENTS else {}),
        allow_promotion_codes=True,
        client_reference_id=str(user.id),
        success_url=f"{APP_URL}/dashboard/billing.html?success=1",
        cancel_url=f"{APP_URL}/dashboard/billing.html?cancelled=1",
        metadata={"lyra_user_id": str(user.id), "plan": plan},
    )
    return {"checkout_url": session.url}


@router.post("/portal")
def create_portal(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe customer portal session to manage billing."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe not configured.")
    if not user.stripe_customer_id:
        raise HTTPException(400, "No billing account yet. Upgrade to Pro first.")

    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{APP_URL}/dashboard/billing.html",
    )
    return {"portal_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe events (subscription created/updated/deleted)."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook secret not configured.")

    stripe = _stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {e}")

    # Newer stripe-python objects aren't dicts; work on plain dicts below.
    event = event.to_dict() if hasattr(event, "to_dict") else event
    et = event["type"]
    data = event["data"]["object"]

    # Lyra Watch Pro, API credits and sponsor slots are handled separately and never touch user.tier.
    from lyra.api import watch_access
    if watch_access.handle_webhook(et, data, db, stripe):
        return {"received": True}

    if et == "checkout.session.completed" and data.get("subscription"):
        # Upgrade as soon as checkout finishes rather than waiting for the subscription event.
        sub = stripe.Subscription.retrieve(data["subscription"])
        et, data = "customer.subscription.updated", (sub.to_dict() if hasattr(sub, "to_dict") else sub)

    if et in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id     = data.get("customer")
        subscription_id = data.get("id")
        status          = data.get("status")
        # The plan comes from the price: its lyra_plan metadata or lookup key, else a configured ID.
        # This Stripe account also sells ChemWarden plans; a price that isn't a Lyra plan is ignored.
        items = data.get("items", {}).get("data", [])
        price = items[0].get("price", {}) if items else {}
        _resolve_prices()
        plan = (price.get("metadata") or {}).get("lyra_plan") \
            or next((p for p, k in LOOKUP_KEYS.items() if k == price.get("lookup_key")), None) \
            or next((p for p, pid in PRICE_IDS.items() if pid and pid == price.get("id")), None)

        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user and plan in PLANS:
            user.stripe_subscription_id = subscription_id
            user.tier = plan if status in ("active", "trialing") else "free"
            db.commit()
            logger.info(f"User {user.email} tier → {user.tier}")

    elif et == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            user.tier = "free"
            user.stripe_subscription_id = None
            db.commit()
            logger.info(f"Subscription cancelled for {user.email}")

    return {"received": True}
