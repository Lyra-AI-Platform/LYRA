"""
LyraAuth — FastAPI Backend
Challenge serving, verification, site registration, training data export.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from lyra.authenticator.engine import challenge_engine, ChallengeResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["lyraauth"])


# ── Models ────────────────────────────────────────────────────────────────────

class SiteRegistration(BaseModel):
    domain: str
    contact_email: str

class VerifyRequest(BaseModel):
    challenge_id: str
    session_id: str
    answer: str
    answer_time_ms: int
    site_key: str
    user_agent: str = ""

class ServerVerifyRequest(BaseModel):
    """Website backend calls this to confirm a token is genuine."""
    secret_key: str
    token: str


# ── Challenge Endpoints ───────────────────────────────────────────────────────

@router.get("/challenge")
async def get_challenge(site_key: str = "", difficulty: str = "normal"):
    """Serve a fresh challenge to the widget."""
    c = challenge_engine.generate_challenge(difficulty)
    return {
        "id": c.id,
        "type": c.type,
        "prompt": c.prompt,
        "options": c.options,
        "expires_in": 300,
        # Never reveal correct_answer to client
    }


@router.post("/verify")
async def verify_challenge(req: VerifyRequest):
    """Verify a challenge response. Called by the widget."""
    resp = ChallengeResponse(
        challenge_id=req.challenge_id,
        session_id=req.session_id,
        answer=req.answer,
        answer_time_ms=req.answer_time_ms,
        site_key=req.site_key,
        user_agent=req.user_agent,
    )
    is_human, confidence, token = challenge_engine.verify_response(resp)

    if is_human:
        return {"success": True, "token": token, "confidence": round(confidence, 2)}
    return {"success": False, "message": "Verification failed. Please try again."}


@router.post("/siteverify")
async def server_verify(req: ServerVerifyRequest):
    """
    Server-to-server verification (like Google's reCAPTCHA siteverify).
    Website backend calls this with the token to confirm it's genuine.

    POST /api/auth/siteverify
    { "secret_key": "lyrasecret_...", "token": "lyraauth_..." }
    """
    # In production: validate secret_key against site registry
    # and verify token hasn't been used before (replay protection)
    is_valid = req.token.startswith("lyraauth_") and len(req.token) == 41
    return {
        "success": is_valid,
        "challenge_ts": None,
        "hostname": None,
        "score": 0.9 if is_valid else 0.0,
    }


# ── Site Registration ─────────────────────────────────────────────────────────

@router.post("/register")
async def register_site(req: SiteRegistration):
    """Register a new website to use LyraAuth."""
    if not req.domain or not req.contact_email:
        raise HTTPException(status_code=400, detail="Domain and email required")
    keys = challenge_engine.register_site(req.domain, req.contact_email)
    return {
        "success": True,
        "site_key": keys["site_key"],
        "secret_key": keys["secret_key"],
        "integration_snippet": _build_snippet(keys["site_key"]),
        "server_verify_url": "/api/auth/siteverify",
        "message": (
            "Keep your secret_key private — use it server-side only. "
            "Your site_key is public and goes in the HTML widget."
        ),
    }


# ── Training Data ─────────────────────────────────────────────────────────────

@router.get("/training/stats")
async def training_stats():
    """How much training data has been collected."""
    return challenge_engine.get_training_stats()


@router.get("/training/export")
async def export_training(date: Optional[str] = None):
    """Export training data in {prompt, completion} format for fine-tuning."""
    records = challenge_engine.export_training_data(date)
    return {"count": len(records), "records": records}


# ── Status & Demo ──────────────────────────────────────────────────────────────

@router.get("/status")
async def auth_status():
    return {
        "service": "LyraAuth",
        "version": "1.0.0",
        "challenges_served": challenge_engine.challenges_served,
        "challenges_passed": challenge_engine.challenges_passed,
        "training_records": challenge_engine.training_records,
        "registered_sites": len(challenge_engine._site_keys),
    }


@router.get("/demo", response_class=HTMLResponse)
async def demo_page():
    """Live demo page — try LyraAuth right in the browser."""
    return HTMLResponse(_DEMO_HTML)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_snippet(site_key: str) -> str:
    return f"""<!-- LyraAuth — add before </body> -->
<script src="https://auth.lyra.ai/lyraauth.js" async></script>
<div class="lyraauth" data-sitekey="{site_key}"></div>

<!-- Server-side verification (Node.js example) -->
<!--
const res = await fetch('https://auth.lyra.ai/api/auth/siteverify', {{
  method: 'POST',
  body: JSON.stringify({{ secret_key: 'YOUR_SECRET', token: req.body.lyraauth_token }})
}});
const {{ success }} = await res.json();
-->"""


_DEMO_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LyraAuth Demo</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: linear-gradient(135deg, #667eea10, #764ba220);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .demo-card {
      background: white;
      border-radius: 20px;
      padding: 40px;
      max-width: 480px;
      width: 100%;
      box-shadow: 0 20px 60px rgba(0,0,0,0.1);
    }
    h1 { font-size: 24px; color: #1a202c; margin-bottom: 6px; }
    p { font-size: 14px; color: #718096; margin-bottom: 24px; line-height: 1.6; }
    .form-row { margin-bottom: 16px; }
    label { font-size: 13px; font-weight: 600; color: #4a5568; display: block; margin-bottom: 6px; }
    input[type=email] {
      width: 100%; padding: 10px 14px;
      border: 1.5px solid #e2e8f0; border-radius: 10px;
      font-size: 14px; outline: none; transition: border-color 0.2s;
    }
    input[type=email]:focus { border-color: #667eea; }
    button[type=submit] {
      width: 100%; padding: 12px;
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: white; border: none; border-radius: 10px;
      font-size: 15px; font-weight: 700; cursor: pointer; margin-top: 16px;
      transition: opacity 0.2s;
    }
    button[type=submit]:hover { opacity: 0.9; }
    .token-display {
      margin-top: 16px; padding: 12px;
      background: #f0fff4; border: 1.5px solid #68d391;
      border-radius: 10px; font-size: 12px; color: #276749;
      font-family: monospace; word-break: break-all; display: none;
    }
    .powered {
      text-align: center; margin-top: 24px;
      font-size: 11px; color: #a0aec0;
    }
    .powered a { color: #667eea; text-decoration: none; }
  </style>
</head>
<body>
  <div class="demo-card">
    <h1>✦ LyraAuth Demo</h1>
    <p>Try the world's most modern CAPTCHA alternative. Answer one quick question to prove you're human — and help train an AI while you're at it.</p>

    <form id="demo-form">
      <div class="form-row">
        <label>Email address</label>
        <input type="email" placeholder="you@example.com" required />
      </div>

      <!-- LyraAuth Widget -->
      <div class="lyraauth" data-sitekey="lyra_demo_key_0000000000000000"></div>

      <button type="submit">Continue →</button>

      <div class="token-display" id="token-display"></div>
    </form>

    <div class="powered">
      Protected by <a href="https://auth.lyra.ai">LyraAuth</a> ·
      Your answers train <a href="https://github.com/Lyra-AI-Platform/LYRA">Lyra AI</a>
    </div>
  </div>

  <script src="/lyraauth.js"></script>
  <script>
    document.getElementById('demo-form').addEventListener('submit', function(e) {
      e.preventDefault();
      const token = document.querySelector('input[name=lyraauth_token]');
      if (!token || !token.value) {
        alert('Please complete the human verification first!');
        return;
      }
      const display = document.getElementById('token-display');
      display.style.display = 'block';
      display.textContent = '✓ Verified! Token: ' + token.value;
    });
  </script>
</body>
</html>"""
