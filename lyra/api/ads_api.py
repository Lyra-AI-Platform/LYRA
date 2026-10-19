"""Sponsor slots on Lyra Watch.

Anyone with an account can book a slot (a headline, a line of text and a link) for a number of
weeks and pay through Stripe Checkout. A paid slot goes live only after the site owner approves
it (LYRA_ADMIN_EMAILS); a rejected one is refunded from the Stripe dashboard. Free visitors see a
sponsor, or Lyra's own offer when none is live; Watch Pro subscribers see no ads.

No ad networks and no tracking cookies: an impression and a click are counted, nothing else.
"""
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Dict
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.api import watch_access
from lyra.api.users_api import get_current_user
from lyra.db.database import get_db
from lyra.db.models import Sponsor, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ads", tags=["ads"])

WEEK_CENTS = int(os.getenv("LYRA_SPONSOR_WEEK_CENTS", 4900))
MAX_WEEKS = 8


def _admins():
    return {e.strip().lower() for e in os.getenv("LYRA_ADMIN_EMAILS", "").split(",") if e.strip()}


def _now():
    return datetime.now(timezone.utc)


def _aware(d):
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d


HOUSE = [
    {"headline": "See who moves the market, as it happens",
     "body": "Lyra Watch Pro: the real-time live stream, every person's market impact and said & traded.",
     "url": "/watch/account/", "cta": "Go Pro"},
    {"headline": "Building an AI agent? Give it Lyra Watch",
     "body": "Real-time public-figure and market-impact data over a JSON API. 100 free credits with your first key.",
     "url": "/watch/account/#api", "cta": "Get a key"},
    {"headline": "Advertise to people who follow the market",
     "body": "Put your product in front of Lyra Watch readers. Self-serve, from one week.",
     "url": "/advertise/", "cta": "Advertise"},
]


def live_sponsors(db: Session):
    now = _now()
    return [s for s in db.query(Sponsor).filter(Sponsor.status == "live").all()
            if _aware(s.starts_at) and _aware(s.starts_at) <= now < _aware(s.ends_at)]


@router.get("/slot")
def slot(db: Session = Depends(get_db), viewer: watch_access.Viewer = Depends(watch_access.identify("person"))):
    """The ad for a free visitor: a live sponsor, otherwise one of Lyra's own offers. Nothing for
    subscribers and API keys."""
    if viewer.full:
        return {"kind": "none"}
    live = live_sponsors(db)
    if live:
        s = random.choice(live)
        s.impressions += 1
        db.commit()
        return {"kind": "sponsor", "id": s.id, "headline": s.headline, "body": s.body,
                "url": f"/api/ads/click/{s.id}", "cta": "Visit", "label": "Sponsored"}
    return {"kind": "house", **random.choice(HOUSE), "label": "From Lyra"}


@router.get("/click/{sid}")
def click(sid: int, db: Session = Depends(get_db)):
    s = db.get(Sponsor, sid)
    if not s or s.status != "live":
        return RedirectResponse("/watch/", 302)
    s.clicks += 1
    db.commit()
    return RedirectResponse(s.url, 302)


class Booking(BaseModel):
    headline: str
    body: str = ""
    url: str
    weeks: int = 1


@router.get("/rates")
def rates():
    return {"currency": watch_access.CURRENCY, "week_cents": WEEK_CENTS, "max_weeks": MAX_WEEKS,
            "rules": "Lawful products only; no gambling, adult, weapons, political campaigns or financial promotions "
                     "that need regulatory approval. Every slot is reviewed before it goes live; a declined slot is refunded."}


@router.post("/book")
def book(b: Booking, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    headline, body, url = b.headline.strip(), b.body.strip(), b.url.strip()
    if not 3 <= len(headline) <= 70 or len(body) > 160:
        raise HTTPException(400, "Headline 3-70 characters, text up to 160.")
    if urlparse(url).scheme != "https" or not urlparse(url).netloc:
        raise HTTPException(400, "The link must be a full https:// address.")
    weeks = min(max(b.weeks, 1), MAX_WEEKS)
    s = Sponsor(user_id=user.id, headline=headline, body=body, url=url, weeks=weeks, status="unpaid")
    db.add(s)
    db.commit()
    stripe = watch_access._stripe()
    session = watch_access._checkout(
        stripe, customer=watch_access._customer(user, db, stripe), mode="payment", client_reference_id=str(user.id),
        line_items=[{"quantity": weeks, "price_data": {
            "currency": watch_access.CURRENCY, "unit_amount": WEEK_CENTS,
            "product_data": {"name": "Lyra Watch sponsor slot (1 week)", "tax_code": watch_access.TAX_CODE}}}],
        metadata={"lyra_user_id": str(user.id), "product": "sponsor", "sponsor_id": str(s.id)},
        success_url=f"{watch_access.APP_URL}/advertise/?paid=1", cancel_url=f"{watch_access.APP_URL}/advertise/?cancelled=1")
    s.stripe_session_id = session.id
    db.commit()
    return {"checkout_url": session.url, "id": s.id}


def mark_paid(sid: int, session: Dict, db: Session):
    s = db.get(Sponsor, sid)
    if s and s.status == "unpaid" and session.get("payment_status") == "paid":
        s.status = "paid"
        db.commit()
        logger.info(f"Sponsor slot {sid} paid; waiting for approval")


def _row(s: Sponsor) -> Dict:
    return {"id": s.id, "headline": s.headline, "body": s.body, "url": s.url, "weeks": s.weeks, "status": s.status,
            "impressions": s.impressions, "clicks": s.clicks,
            "starts_at": s.starts_at.isoformat() if s.starts_at else None,
            "ends_at": s.ends_at.isoformat() if s.ends_at else None}


@router.get("/mine")
def mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"slots": [_row(s) for s in db.query(Sponsor).filter(Sponsor.user_id == user.id, Sponsor.status != "unpaid")
                      .order_by(Sponsor.id.desc()).all()],
            "admin": user.email.lower() in _admins()}


def _admin(user: User = Depends(get_current_user)) -> User:
    if user.email.lower() not in _admins():
        raise HTTPException(403, "Owner only")
    return user


@router.get("/admin")
def admin_list(user: User = Depends(_admin), db: Session = Depends(get_db)):
    return {"slots": [_row(s) for s in db.query(Sponsor).filter(Sponsor.status.in_(("paid", "live")))
                      .order_by(Sponsor.id.desc()).all()]}


@router.post("/admin/{sid}/{action}")
def admin_decide(sid: int, action: str, user: User = Depends(_admin), db: Session = Depends(get_db)):
    s = db.get(Sponsor, sid)
    if not s or action not in ("approve", "reject", "stop"):
        raise HTTPException(404, "No such slot or action")
    if action == "approve" and s.status == "paid":
        s.status, s.starts_at = "live", _now()
        s.ends_at = s.starts_at + timedelta(weeks=s.weeks)
    elif action in ("reject", "stop"):
        s.status = "rejected"   # refund it from the Stripe dashboard
    db.commit()
    return _row(s)
