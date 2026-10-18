"""
Sites / API-key management API.

GET    /api/sites              — list current user's sites
POST   /api/sites              — create a site (generates site_key + secret_key)
GET    /api/sites/{id}         — get one site
DELETE /api/sites/{id}         — deactivate a site
POST   /api/sites/{id}/rotate  — regenerate secret_key
GET    /api/sites/{id}/usage   — last 30 days usage
"""
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.db.database import get_db
from lyra.db.models import Site, UsageRecord, User
from lyra.api.users_api import get_current_user

router = APIRouter(prefix="/api/sites", tags=["sites"])

FREE_TIER_MONTHLY_LIMIT = 10_000


# ── Schemas ───────────────────────────────────────────────────────────────────

class SiteCreate(BaseModel):
    name: str = "My Site"
    domain: str = ""

class SiteOut(BaseModel):
    id: int
    name: str
    domain: str
    site_key: str
    secret_key: str
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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SiteOut])
def list_sites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Site).filter(Site.user_id == user.id).all()


@router.post("", response_model=SiteOut, status_code=201)
def create_site(
    req: SiteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Free tier: max 3 sites
    if user.tier == "free":
        count = db.query(Site).filter(Site.user_id == user.id, Site.is_active == True).count()
        if count >= 3:
            raise HTTPException(403, "Free tier allows up to 3 sites. Upgrade to Pro for unlimited.")

    site = Site(
        user_id=user.id,
        name=req.name.strip() or "My Site",
        domain=req.domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0],
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_site_or_404(site_id, user, db)


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
    site.secret_key = "lyra_secret_" + secrets.token_urlsafe(32)
    db.commit()
    db.refresh(site)
    return {"success": True, "secret_key": site.secret_key}


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
    limit = FREE_TIER_MONTHLY_LIMIT if user.tier == "free" else None

    return {
        "site_id": site_id,
        "month_total": month_total,
        "monthly_limit": limit,
        "remaining": max(0, limit - month_total) if limit else None,
        "daily": daily,
    }
