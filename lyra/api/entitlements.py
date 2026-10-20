"""Who may use what.

Everything on lyraauth.com is paid. A new account gets a short trial so people
can judge the product, then it needs a plan. Rules live here so every API
applies the same ones:

  * paid  = tier in PAID_TIERS (set by the Stripe webhook)
  * trial = account younger than TRIAL_DAYS and still under each feature's allowance
  * after that, protected routes answer 402 with an upgrade URL

Trial use is counted in the trial_usage table (lyra/db/models.py).
"""
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from lyra.db.database import get_db
from lyra.db.models import TrialUsage, User
from lyra.api.users_api import get_current_user

PAID_TIERS = ("starter", "pro", "business", "enterprise")
TRIAL_DAYS = int(os.environ.get("LYRA_TRIAL_DAYS", 14))
# Lifetime allowances during the trial. After any one is used up, that feature needs a plan.
TRIAL_LIMITS: Dict[str, int] = {
    "market": int(os.environ.get("LYRA_TRIAL_MARKET_READINGS", 3)),   # Tremor Index readings
    "chat": int(os.environ.get("LYRA_TRIAL_CHAT_MESSAGES", 20)),      # Lyra chat messages
}
UPGRADE_URL = "/dashboard/billing.html"
FEATURE_NAMES = {"market": "Tremor Index readings", "chat": "Lyra chat messages", "watch_live": "Lyra Watch Live"}


def is_paid(user: User) -> bool:
    return (user.tier or "free") in PAID_TIERS


def trial_days_left(user: User) -> int:
    created = user.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    end = created + timedelta(days=TRIAL_DAYS)
    left = (end - datetime.now(timezone.utc)).total_seconds() / 86400
    return max(0, math.ceil(left))   # a brand-new account shows the full 14 days


def _usage(user: User, feature: str, db: Session) -> TrialUsage:
    row = db.query(TrialUsage).filter(TrialUsage.user_id == user.id, TrialUsage.feature == feature).first()
    if not row:
        row = TrialUsage(user_id=user.id, feature=feature, count=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def status(user: User, db: Session) -> Dict:
    """What the dashboard shows: plan, trial days left, allowance used per feature."""
    used = {f: _usage(user, f, db).count for f in TRIAL_LIMITS}
    days = trial_days_left(user)
    return {
        "tier": user.tier or "free",
        "paid": is_paid(user),
        "trial": None if is_paid(user) else {
            "days_left": days, "expired": days == 0,
            "used": used, "limits": TRIAL_LIMITS,
            "remaining": {f: max(0, TRIAL_LIMITS[f] - used[f]) for f in TRIAL_LIMITS},
        },
        "upgrade_url": UPGRADE_URL,
    }


def _payment_required(feature: str, reason: str) -> HTTPException:
    return HTTPException(402, {"error": "payment_required", "feature": feature, "reason": reason,
                               "message": f"Your trial of {FEATURE_NAMES.get(feature, feature)} has ended. "
                                          "Choose a plan to continue.",
                               "upgrade_url": UPGRADE_URL})


def check(user: User, feature: str, db: Session, consume: int = 0) -> None:
    """Raise 402 unless the user may use `feature`. With consume>0, also spends that much trial allowance."""
    if is_paid(user):
        return
    if trial_days_left(user) == 0:
        raise _payment_required(feature, "trial_expired")
    row = _usage(user, feature, db)
    limit = TRIAL_LIMITS.get(feature, 0)
    if row.count + consume > limit:
        raise _payment_required(feature, "trial_allowance_used")
    if consume:
        row.count += consume
        row.last_used = datetime.now(timezone.utc)
        db.commit()


def require(feature: str, consume: int = 0):
    """FastAPI dependency: the signed-in user, or 402."""
    def dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        check(user, feature, db, consume)
        return user
    return dep


def require_paid(feature: str):
    """FastAPI dependency for subscriber-only features: no trial allowance, a plan or 402."""
    def dep(user: User = Depends(get_current_user)) -> User:
        if not is_paid(user):
            raise HTTPException(402, {"error": "payment_required", "feature": feature, "reason": "subscribers_only",
                                      "message": f"{FEATURE_NAMES.get(feature, feature)} is for subscribers. "
                                                 "Choose a plan to watch.",
                                      "upgrade_url": UPGRADE_URL})
        return user
    return dep


def user_from_conn(conn, db: Session) -> Optional[User]:
    """The signed-in user outside the HTTP dependency system (WebSockets, middleware)."""
    from lyra.api import sessions
    return sessions.user_from_cookie(conn, db)
