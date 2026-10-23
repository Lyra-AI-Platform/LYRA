"""The owner's dashboard data (website/admin/). Owner only (LYRA_ADMIN_EMAILS); everyone else
gets 404, as if it didn't exist.

  GET /api/admin/overview   accounts, plans, ads waiting, feedback, newswire and AI health
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lyra.api import entitlements
from lyra.api.users_api import get_current_user
from lyra.db.database import get_db
from lyra.db.models import Feedback, LoginSession, OAuthIdentity, Sponsor, User, WatchSubscription

router = APIRouter(prefix="/api/admin", tags=["admin"])


def owner(user: User = Depends(get_current_user)) -> User:
    if not entitlements.is_admin(user):
        raise HTTPException(404, "Not Found")
    return user


@router.get("/overview")
def overview(user: User = Depends(owner), db: Session = Depends(get_db)):
    from lyra.core import ollama_backend
    from lyra.newswire.store import get_wire
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    users = db.query(User).all()
    created = [u.created_at if (u.created_at and u.created_at.tzinfo) else (u.created_at or now).replace(tzinfo=timezone.utc) for u in users]
    providers = {}
    for (p,) in db.query(OAuthIdentity.provider).all():
        providers[p] = providers.get(p, 0) + 1
    wire = get_wire().stats()
    return {
        "accounts": {"total": len(users), "new_7d": sum(c >= week for c in created),
                     "paying": sum((u.tier or "free") in entitlements.PAID_TIERS for u in users),
                     "on_trial": sum(entitlements.trial_days_left(u) > 0 and (u.tier or "free") not in entitlements.PAID_TIERS for u in users),
                     "watch_pro": db.query(WatchSubscription).filter(WatchSubscription.status.in_(("active", "trialing"))).count(),
                     "signed_in_now": db.query(LoginSession).filter(LoginSession.last_seen >= now - timedelta(minutes=30)).count(),
                     "sign_in_methods": providers},
        "ads": {"waiting_for_approval": db.query(Sponsor).filter(Sponsor.status == "paid").count(),
                "live": db.query(Sponsor).filter(Sponsor.status == "live").count()},
        "feedback": {"total": db.query(Feedback).count(),
                     "last_7d": db.query(Feedback).filter(Feedback.created_at >= week).count(),
                     "not_emailed": db.query(Feedback).filter(Feedback.emailed == False).count()},  # noqa: E712
        "newswire": {k: wire[k] for k in ("articles", "added_last_24h", "countries", "languages", "publishers", "by_kind")},
        "newswire_failing": [f["source"] for f in wire["feeds"] if f["last_error"]][:20],
        "lyra_model": {"on": ollama_backend.enabled(), "name": ollama_backend.model() or None},
    }
