"""
Sites / API-key management API.

GET    /api/sites              — list current user's sites
POST   /api/sites              — create a site (generates site_key + secret_key)
GET    /api/sites/{id}         — get one site
DELETE /api/sites/{id}         — deactivate a site
POST   /api/sites/{id}/rotate  — regenerate secret_key
GET    /api/sites/{id}/usage   — last 30 days usage
"""
import secrets as _secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.api import plans
from lyra.api.users_api import get_current_user
from lyra.authenticator.guard import hash_secret
from lyra.db.database import get_db
from lyra.db.models import Site, UsageRecord, User

router = APIRouter(prefix="/api/sites", tags=["sites"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SiteCreate(BaseModel):
    name: str = "My Site"
    domain: str = ""

class SiteOut(BaseModel):
    id: int
    name: str
    domain: str
    site_key: str
    secret_key: Optional[str] = None   # only in the response that created it
    secret_hint: str = ""
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_site_or_404(site_id: int, user: User, db: Session) -> Site:
    site = db.query(Site).filter(
        Site.id == site_id, Site.user_id == user.id
    ).first()
    if not site:
        raise HTTPException(404, "Site not found")
    return site


def _monthly_usage(site_id: int, db: Session) -> int:
    """Count verifications in the current calendar month."""
    now = datetime.now(timezone.utc)
    prefix = now.strftime("%Y-%m")
    records = db.query(UsageRecord).filter(
        UsageRecord.site_id == site_id,
        UsageRecord.date.like(f"{prefix}%"),
    ).all()
    return sum(r.count for r in records)


def _account_usage(user_id: int, db: Session) -> int:
    """Verifications this calendar month across all the account's sites."""
    prefix = datetime.now(timezone.utc).strftime("%Y-%m")
    records = db.query(UsageRecord).join(Site, UsageRecord.site_id == Site.id).filter(
        Site.user_id == user_id, UsageRecord.date.like(f"{prefix}%")).all()
    return sum(r.count for r in records)


def _effective_tier(user: User) -> str:
    from lyra.api.entitlements import is_admin
    return "enterprise" if is_admin(user) else (user.tier or "free")


def month_limit_reached(user: User, db: Session) -> bool:
    return plans.over_monthly_limit(_effective_tier(user), _account_usage(user.id, db))


def _new_secret(site: Site) -> str:
    """Store a fresh secret's hash on the site and return the secret, for showing once."""
    secret = "lyra_secret_" + _secrets.token_urlsafe(32)
    site.secret_key = hash_secret(secret)
    site.secret_hint = secret[-4:]
    return secret


def _out(site: Site, secret: Optional[str] = None) -> SiteOut:
    return SiteOut(id=site.id, name=site.name, domain=site.domain, site_key=site.site_key, secret_key=secret,
                   secret_hint=site.secret_hint or "", is_active=site.is_active, created_at=site.created_at)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SiteOut])
def list_sites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_out(s) for s in db.query(Site).filter(Site.user_id == user.id).all()]


@router.post("", response_model=SiteOut, status_code=201)
def create_site(
    req: SiteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = db.query(Site).filter(Site.user_id == user.id, Site.is_active == True).count()  # noqa: E712
    tier = _effective_tier(user)
    if not plans.can_add_site(tier, count):
        allowed = plans.site_limits(tier)[1]
        raise HTTPException(402, {"error": "payment_required", "feature": "sites",
                                  "message": f"Your {plans.plan_name(tier)} plan includes {allowed} "
                                             f"site{'' if allowed == 1 else 's'}. Choose a bigger plan to add more.",
                                  "upgrade_url": "/dashboard/billing.html"})

    site = Site(
        user_id=user.id,
        name=req.name.strip() or "My Site",
        domain=req.domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0],
    )
    secret = _new_secret(site)
    db.add(site)
    db.commit()
    db.refresh(site)
    return _out(site, secret)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _out(_get_site_or_404(site_id, user, db))


@router.delete("/{site_id}")
def delete_site(
    site_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    site = _get_site_or_404(site_id, user, db)
    site.is_active = False
    db.commit()
    return {"success": True, "message": "Site deactivated"}


@router.post("/{site_id}/rotate")
def rotate_secret(
    site_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Regenerate the secret key (invalidates old one immediately)."""
    site = _get_site_or_404(site_id, user, db)
    secret = _new_secret(site)
    db.commit()
    return {"success": True, "secret_key": secret, "secret_hint": site.secret_hint}


@router.get("/{site_id}/usage")
def get_usage(
    site_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    site = _get_site_or_404(site_id, user, db)

    # Last 30 days
    now = datetime.now(timezone.utc)
    days = []
    for i in range(30):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        days.append(d)

    records = {
        r.date: r.count
        for r in db.query(UsageRecord).filter(
            UsageRecord.site_id == site_id,
            UsageRecord.date.in_(days),
        ).all()
    }

    daily = [{"date": d, "count": records.get(d, 0)} for d in reversed(days)]
    month_total = _monthly_usage(site_id, db)
    limit = plans.site_limits(_effective_tier(user))[0]
    account_total = _account_usage(user.id, db)

    return {
        "site_id": site_id,
        "month_total": month_total,
        "account_total": account_total,
        "monthly_limit": limit,
        "remaining": max(0, limit - account_total) if limit else None,
        "daily": daily,
    }
