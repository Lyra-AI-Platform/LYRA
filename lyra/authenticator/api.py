"""
LyraAuth — FastAPI Backend
Challenge serving, verification, site registration, training data export.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.authenticator.engine import challenge_engine, ChallengeResponse
from lyra.db.database import get_db
from lyra.db.models import Site, UsageRecord, VerifiedToken

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["lyraauth"])

TOKEN_TTL_MINUTES = 5
FREE_MONTHLY_LIMIT = 10_000


# ── Schemas ───────────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    challenge_id: str
    session_id: str
    answer: str
    answer_time_ms: int
    site_key: str
    user_agent: str = ""

class ServerVerifyRequest(BaseModel):
    """Website backend POSTs this to confirm a widget token is genuine."""
    secret_key: str
    token: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _bump_usage(site_id: int, db: Session):
    """Increment today's usage counter for the given site."""
    today = _today()
    record = db.query(UsageRecord).filter(
        UsageRecord.site_id == site_id,
        UsageRecord.date == today,
    ).first()
    if record:
        record.count += 1
    else:
        db.add(UsageRecord(site_id=site_id, date=today, count=1))
    db.commit()


# ── Challenge endpoints ───────────────────────────────────────────────────────

@router.get("/challenge")
async def get_challenge(site_key: str = "", difficulty: str = "normal"):
    """Serve a fresh challenge to the widget."""
    c = challenge_engine.generate_challenge(difficulty)
    return {
        "id": c.id,
        "type": c.type,
        "prompt": c.prompt,
        "options": c.options,
        "expires_in": TOKEN_TTL_MINUTES * 60,
    }


@router.post("/verify")
async def verify_challenge(req: VerifyRequest, db: Session = Depends(get_db)):
    """
    Verify a challenge response from the widget.
    If human, issue a short-lived one-use token and store it in the DB.
    """
    resp = ChallengeResponse(
        challenge_id=req.challenge_id,
        session_id=req.session_id,
        answer=req.answer,
        answer_time_ms=req.answer_time_ms,
        site_key=req.site_key,
        user_agent=req.user_agent,
    )
    is_human, confidence, raw_token = challenge_engine.verify_response(resp)

    if not is_human:
        return {"success": False, "message": "Verification failed. Please try again."}

    # Look up the site by site_key
    site = db.query(Site).filter(
        Site.site_key == req.site_key,
        Site.is_active == True,
    ).first()

    site_id = site.id if site else None

    # Check free-tier limit
    if site and site.owner.tier == "free":
        now = datetime.now(timezone.utc)
        prefix = now.strftime("%Y-%m")
        records = db.query(UsageRecord).filter(
            UsageRecord.site_id == site_id,
            UsageRecord.date.like(f"{prefix}%"),
        ).all()
        month_total = sum(r.count for r in records)
        if month_total >= FREE_MONTHLY_LIMIT:
            return {
                "success": False,
                "message": "Monthly verification limit reached. Upgrade to Pro.",
                "upgrade_url": "https://lyraauth.com/dashboard/billing.html",
            }

    # Store the verified token in the DB (for replay protection in siteverify)
    token = "lyraauth_" + secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)

    if site_id:
        db.add(VerifiedToken(token=token, site_id=site_id, expires_at=expires))
        db.commit()

    return {"success": True, "token": token, "confidence": round(confidence, 2)}


@router.post("/siteverify")
async def server_verify(req: ServerVerifyRequest, db: Session = Depends(get_db)):
    """
    Server-to-server verification (matches Google's reCAPTCHA siteverify API).
    Your backend POSTs the secret_key + token to confirm the user passed the widget.

    Validates:
    1. secret_key exists and belongs to an active site
    2. Token exists in DB and hasn't been used
    3. Token hasn't expired (5-minute TTL)
    """
    # Validate secret key
    site = db.query(Site).filter(
        Site.secret_key == req.secret_key,
        Site.is_active == True,
    ).first()
    if not site:
        return {"success": False, "error-codes": ["invalid-secret-key"]}

    # Validate token
    now = datetime.now(timezone.utc)
    vt = db.query(VerifiedToken).filter(
        VerifiedToken.token == req.token,
        VerifiedToken.site_id == site.id,
    ).first()

    if not vt:
        return {"success": False, "error-codes": ["invalid-token"]}
    if vt.used:
        return {"success": False, "error-codes": ["token-already-used"]}
    if vt.expires_at.replace(tzinfo=timezone.utc) < now:
        return {"success": False, "error-codes": ["token-expired"]}

    # Consume the token (one-use only)
    vt.used = True
    _bump_usage(site.id, db)

    return {
        "success": True,
        "hostname": site.domain or None,
        "challenge_ts": vt.created_at.isoformat(),
        "score": 0.9,
    }


# ── Legacy site registration (kept for backwards compat) ──────────────────────

@router.post("/register")
async def register_site_legacy(request: Request, db: Session = Depends(get_db)):
    """
    Quick site registration without a user account.
    Prefer the dashboard flow (/dashboard → create site) for full features.
    """
    body = await request.json()
    domain = body.get("domain", "")
    email  = body.get("email") or body.get("contact_email", "")
    if not domain or not email:
        raise HTTPException(400, "domain and email required")

    site = Site(name=domain, domain=domain)
    # Assign to a guest user slot — sites without user_id get no dashboard access
    # (They still work for verification but can't be managed)
    db.add(site)
    try:
        db.commit()
        db.refresh(site)
    except Exception:
        db.rollback()
        raise HTTPException(500, "Could not register site")

    return {
        "success": True,
        "site_key": site.site_key,
        "secret_key": site.secret_key,
        "message": (
            "Keep your secret_key private — server-side only. "
            "Create an account at lyraauth.com/dashboard to manage your site."
        ),
    }


# ── Training data endpoints ───────────────────────────────────────────────────

@router.get("/training/stats")
async def training_stats():
    return challenge_engine.get_training_stats()

@router.get("/training/export")
async def export_training(date: Optional[str] = None):
    records = challenge_engine.export_training_data(date)
    return {"count": len(records), "records": records}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def auth_status():
    return {
        "service": "LyraAuth",
        "version": "1.1.0",
        "challenges_served": challenge_engine.challenges_served,
        "challenges_passed": challenge_engine.challenges_passed,
        "training_records": challenge_engine.training_records,
    }


# ── Demo page ─────────────────────────────────────────────────────────────────

@router.get("/demo", response_class=HTMLResponse)
async def demo_page():
    return HTMLResponse(_DEMO_HTML)


_DEMO_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LyraAuth Demo</title>
  <style>
    * { box-sizing:border-box; margin:0; padding:0; }
    body {
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:#faf9f7; min-height:100vh;
      display:flex; align-items:center; justify-content:center; padding:20px;
    }
    .card {
      background:#fff; border:1px solid rgba(0,0,0,0.1); border-radius:14px;
      padding:40px; max-width:460px; width:100%;
      box-shadow:0 4px 24px rgba(0,0,0,0.07);
    }
    h1 { font-size:22px; color:#14120e; margin-bottom:6px; letter-spacing:-0.03em; }
    p  { font-size:14px; color:#6e6b67; margin-bottom:24px; line-height:1.6; }
    .form-row { margin-bottom:16px; }
    label { font-size:12px; font-weight:600; color:#14120e; display:block; margin-bottom:6px; text-transform:uppercase; letter-spacing:.05em; }
    input[type=email] {
      width:100%; padding:10px 14px;
      border:1px solid rgba(0,0,0,0.15); border-radius:8px;
      font-size:14px; outline:none; background:#faf9f7; color:#14120e;
    }
    input[type=email]:focus { border-color:rgba(0,0,0,0.4); }
    button[type=submit] {
      width:100%; padding:12px; background:#14120e;
      color:#faf9f7; border:none; border-radius:8px;
      font-size:14px; font-weight:600; cursor:pointer; margin-top:16px;
    }
    .result { margin-top:16px; padding:12px; background:#f0fdf4; border:1px solid #86efac;
      border-radius:8px; font-size:12px; color:#166534; font-family:monospace; display:none; }
    .footer { text-align:center; margin-top:24px; font-size:11px; color:#a8a5a0; }
    .footer a { color:#14120e; }
  </style>
</head>
<body>
  <div class="card">
    <h1>LyraAuth Demo</h1>
    <p>Try the drop-in reCAPTCHA replacement. Answer one quick question to verify you're human.</p>
    <form id="f">
      <div class="form-row">
        <label>Email</label>
        <input type="email" placeholder="you@example.com" required />
      </div>
      <div class="lyraauth" data-sitekey="lyra_sk_demo0000000000000000000000000000"></div>
      <button type="submit">Continue</button>
      <div class="result" id="r"></div>
    </form>
    <div class="footer">Protected by <a href="/">LyraAuth</a> · Your answers train Lyra AI</div>
  </div>
  <script src="/lyraauth.js"></script>
  <script>
    document.getElementById('f').addEventListener('submit', function(e) {
      e.preventDefault();
      const t = document.querySelector('input[name=lyraauth_token]');
      if (!t) { alert('Complete the verification first.'); return; }
      const r = document.getElementById('r');
      r.style.display = 'block';
      r.textContent = 'Verified! Token: ' + t.value;
    });
  </script>
</body>
</html>"""
