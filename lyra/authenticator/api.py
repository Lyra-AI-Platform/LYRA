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

from lyra.api import ratelimit
from lyra.authenticator.engine import challenge_engine, ChallengeResponse
from lyra.authenticator.guard import hash_secret, origin_allowed, parse_siteverify, secret_matches, solved_on
from lyra.db.database import get_db
from lyra.api.users_api import _admin_emails, get_current_user
from lyra.db.models import Site, UsageRecord, User, VerifiedToken

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["lyraauth"])

TOKEN_TTL_MINUTES = 5
PER_IP_PER_MINUTE = 30
# The widget on /api/auth/demo. It works only on lyraauth.com and has no site behind it.
DEMO_SITE_KEY = "lyra_site_demo0000000000000000000000000000"
DEMO_DOMAIN = "lyraauth.com"


# ── Schemas ───────────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    challenge_id: str
    session_id: str
    answer: str
    answer_time_ms: int
    site_key: str
    user_agent: str = ""
    pow_nonce: Optional[int] = None    # solution to the challenge's proof of work
    signals: dict = {}                 # webdriver / interacted / headless, from the widget
    training_answer: Optional[str] = None   # optional answer to the training question (1.4.0+)


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


def _require_site(site_key: str, request: Request, db: Session) -> Optional[Site]:
    """The active site for this key, called from that site's own pages. None means the demo."""
    site = None
    domain = DEMO_DOMAIN
    if site_key != DEMO_SITE_KEY:
        site = db.query(Site).filter(Site.site_key == site_key, Site.is_active == True).first()  # noqa: E712
        if not site:
            raise HTTPException(403, {"error": "invalid-site-key", "message": "Unknown site key."})
        domain = site.domain
    if not origin_allowed(domain, request.headers.get("origin"), request.headers.get("referer")):
        raise HTTPException(403, {"error": "origin-not-allowed",
                                  "message": "This site key isn't registered for this website."})
    return site


# ── Challenge endpoints ───────────────────────────────────────────────────────

@router.get("/challenge")
async def get_challenge(request: Request, site_key: str = "", difficulty: str = "normal",
                        db: Session = Depends(get_db)):
    """Serve a fresh challenge to the widget of a registered site."""
    ratelimit.check(f"lyraauth-challenge:{ratelimit.client_ip(request)}", PER_IP_PER_MINUTE, 60)
    _require_site(site_key, request, db)
    c = challenge_engine.generate_challenge(difficulty, client_key=ratelimit.client_ip(request))
    c.site_key = site_key
    t = c.training
    return {
        "id": c.id,
        "type": c.type,
        "prompt": c.prompt,
        "options": c.options,
        "image": c.display_data.get("image"),
        "length": c.display_data.get("length"),
        "training": {"prompt": t.prompt, "options": t.options} if t and t.options else None,
        "expires_in": TOKEN_TTL_MINUTES * 60,
        "pow": {"alg": "SHA-256", "salt": c.pow_salt, "bits": c.pow_bits},
    }


@router.post("/verify")
async def verify_challenge(req: VerifyRequest, request: Request, db: Session = Depends(get_db)):
    """
    Verify a challenge response from the widget.
    If human, issue a short-lived one-use token and store it in the DB.
    """
    ratelimit.check(f"lyraauth-verify:{ratelimit.client_ip(request)}", PER_IP_PER_MINUTE, 60)
    # Before the answer is scored, so an unregistered caller adds nothing to the training data.
    site = _require_site(req.site_key, request, db)

    resp = ChallengeResponse(
        challenge_id=req.challenge_id,
        session_id=req.session_id,
        answer=req.answer,
        answer_time_ms=req.answer_time_ms,
        site_key=req.site_key,
        user_agent=req.user_agent,
        pow_nonce=req.pow_nonce,
        signals={k: bool(v) for k, v in (req.signals or {}).items() if k in ("webdriver", "interacted", "headless")},
        client_key=ratelimit.client_ip(request),
        training_answer=(req.training_answer or "")[:300] or None,
    )
    is_human, confidence, raw_token = challenge_engine.verify_response(resp)

    if not is_human:
        logger.info("LyraAuth refused an attempt: %s", resp.reason)
        return {"success": False, "message": "Verification failed. Please try again.", "reason": resp.reason}

    site_id = site.id if site else None

    # Every plan has a monthly allowance, shared across the account's sites.
    if site:
        from lyra.api.sites_api import month_limit_reached
        if month_limit_reached(site.owner, db):
            return {
                "success": False,
                "message": "This site has used its verifications for this month.",
                "upgrade_url": "https://lyraauth.com/dashboard/billing.html",
            }

    # Store the verified token in the DB (for replay protection in siteverify)
    token = "lyraauth_" + secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)

    if site_id:
        db.add(VerifiedToken(token=token, site_id=site_id, expires_at=expires, score=round(confidence, 2),
                             hostname=solved_on(request.headers.get("origin"), request.headers.get("referer"))))
        db.commit()

    return {"success": True, "token": token, "confidence": round(confidence, 2)}


@router.post("/siteverify")
async def server_verify(request: Request, db: Session = Depends(get_db)):
    """
    Server-to-server verification (matches Google's reCAPTCHA siteverify API).
    Your backend POSTs the secret_key + token as JSON to confirm the user passed the widget.
    Form-encoded bodies and reCAPTCHA's field names (secret, response) work too.

    Validates:
    1. secret_key exists and belongs to an active site
    2. Token exists in DB and hasn't been used
    3. Token hasn't expired (5-minute TTL)
    """
    secret_key, token = parse_siteverify(await request.body(), request.headers.get("content-type", ""))
    if not secret_key or not token:
        return {"success": False, "error-codes": ["missing-input"]}

    # Validate secret key
    site = db.query(Site).filter(
        Site.secret_key == hash_secret(secret_key),
        Site.is_active == True,
    ).first()
    if not site or not secret_matches(site.secret_key, secret_key):
        return {"success": False, "error-codes": ["invalid-secret-key"]}

    # Validate token
    now = datetime.now(timezone.utc)
    vt = db.query(VerifiedToken).filter(
        VerifiedToken.token == token,
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
    # Trial accounts: a fixed number of verifications, and only while the trial is open.
    owner = site.owner
    if owner is not None:
        from lyra.api.entitlements import is_paid, trial_days_left
        from lyra.api.sites_api import month_limit_reached
        if month_limit_reached(owner, db) or (not is_paid(owner) and trial_days_left(owner) == 0):
            raise HTTPException(402, {"error": "payment_required", "feature": "verifications",
                                      "message": "This site's LyraAuth allowance has run out. The owner needs to choose a plan.",
                                      "upgrade_url": "/dashboard/billing.html"})
    _bump_usage(site.id, db)

    return {
        "success": True,
        # Where it was actually solved. Tokens made before this was recorded fall back to the site's domain.
        "hostname": vt.hostname or site.domain or None,
        "challenge_ts": vt.created_at.isoformat(),
        "score": vt.score,
    }


# ── Legacy site registration (kept for backwards compat) ──────────────────────

@router.post("/register")
async def register_site_legacy():
    """Gone: it handed out keys to anyone without an account, which skipped the plan limits.
    Sites are added from the dashboard (POST /api/sites, signed in)."""
    raise HTTPException(410, {"error": "use_dashboard",
                              "message": "Create an account and add your site at https://lyraauth.com/dashboard/ "
                                         "to get your site key and secret key."})


# ── Training data endpoints ───────────────────────────────────────────────────

def _owner(user: User = Depends(get_current_user)) -> User:
    # Records aren't tagged with the site they came from yet, so an export is everyone's data:
    # only the site owner may take it.
    if user.email.lower() not in _admin_emails():
        raise HTTPException(403, "Training data export for customer accounts is coming soon.")
    return user


@router.get("/training/stats")
async def training_stats(_: User = Depends(_owner)):
    return challenge_engine.get_training_stats()


@router.get("/training/export")
async def export_training(date: Optional[str] = None, _: User = Depends(_owner)):
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
      <div class="lyraauth" data-sitekey="lyra_site_demo0000000000000000000000000000"></div>
      <button type="submit">Continue</button>
      <div class="result" id="r"></div>
    </form>
    <div class="footer">Protected by <a href="/">LyraAuth</a> · Your answers train Lyra AI</div>
  </div>
  <script src="/widget.js"></script>
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
