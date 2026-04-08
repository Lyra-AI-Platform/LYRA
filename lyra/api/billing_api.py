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
from sqlalchemy.orm import Session

from lyra.db.database import get_db
from lyra.db.models import User
from lyra.api.users_api import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])

STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
APP_URL               = os.getenv("APP_URL", "https://lyraauth.com")

# One Stripe Price ID per plan — set these env vars after creating products in Stripe dashboard
PRICE_IDS = {
    "starter":    os.getenv("STRIPE_STARTER_PRICE_ID", ""),
    "pro":        os.getenv("STRIPE_PRO_PRICE_ID", ""),
    "business":   os.getenv("STRIPE_BUSINESS_PRICE_ID", ""),
    "enterprise": os.getenv("STRIPE_ENTERPRISE_PRICE_ID", ""),
}

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
def billing_status(user: User = Depends(get_current_user)):
    return {
        "tier": user.tier,
        "stripe_customer_id": user.stripe_customer_id,
        "has_subscription": bool(user.stripe_subscription_id),
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
    price_id = PRICE_IDS.get(plan, "")
    if not price_id:
        raise HTTPException(503, f"Stripe price ID not configured for plan '{plan}'. "
                                  f"Set STRIPE_{plan.upper()}_PRICE_ID env var.")

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
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
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

    et = event["type"]
    data = event["data"]["object"]

    if et in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id     = data.get("customer")
        subscription_id = data.get("id")
        status          = data.get("status")
        # Determine plan from price ID
        price_id = ""
        items = data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id", "")
        plan = next((p for p, pid in PRICE_IDS.items() if pid and pid == price_id), "pro")

        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
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
