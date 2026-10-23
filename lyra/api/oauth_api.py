"""Sign in with Google, Apple or GitHub.

  GET  /api/oauth/providers                 which providers are set up on this server
  GET  /api/oauth/{provider}/start          off to the provider (?next=/path, ?link=1 to connect)
  GET  /api/oauth/{provider}/callback       back from Google and GitHub
  POST /api/oauth/{provider}/callback       back from Apple (it posts a form)
  GET  /api/oauth/identities                connected accounts, and whether a password is set
  DELETE /api/oauth/{provider}              disconnect one (never the last way to sign in)

Each provider is switched on by its settings (none are needed for the rest of the site):

  google  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  github  GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
  apple   APPLE_CLIENT_ID (the Services ID), APPLE_TEAM_ID, APPLE_KEY_ID,
          APPLE_PRIVATE_KEY (the .p8 text) or APPLE_PRIVATE_KEY_FILE

The redirect URI to register with each is LYRA_PUBLIC_URL (https://lyraauth.com) +
/api/oauth/<provider>/callback.

What keeps it safe:
  - state, PKCE verifier and nonce live in a signed, 10-minute, HttpOnly cookie, so the
    callback only works in the browser that started it (no login CSRF, no code injection)
  - the ID token comes straight from the provider's token endpoint over TLS and its issuer,
    audience, expiry and nonce are all checked
  - only an email the provider says is verified is used
  - a provider never takes over an account that has a password: sign in with the password
    first, then connect the provider from Account. (Otherwise someone could sign up with your
    email and a password of theirs, and keep it after you start using Google.)
  - sign-in itself is the same server-side session as a password sign-in (sessions.py)
"""
import base64
import hashlib
import json
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from lyra.api import ratelimit, sessions
from lyra.api.users_api import NO_PASSWORD, SECRET_KEY, get_current_user, has_password
from lyra.db.database import get_db
from lyra.db.models import OAuthIdentity, User

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

LOGIN = "/dashboard/login.html"
ACCOUNT = "/account/"
STATE_COOKIE = "lyra_oauth"
STATE_TTL = 600
SAFE_NEXT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~/?=&%+#")

PROVIDERS = {
    "google": {
        "label": "Google",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
        "issuers": ("https://accounts.google.com", "accounts.google.com"),
        "env": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    },
    "github": {
        "label": "GitHub",
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
        "env": ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"),
    },
    "apple": {
        "label": "Apple",
        "authorize": "https://appleid.apple.com/auth/authorize",
        "token": "https://appleid.apple.com/auth/token",
        "scope": "name email",
        "issuers": ("https://appleid.apple.com",),
        "env": ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID"),
    },
}

# Swapped in tests so no request leaves the machine.
http_client = lambda: httpx.Client(timeout=10, headers={"User-Agent": "LyraAuth/1.0"})  # noqa: E731


def public_url() -> str:
    return os.getenv("LYRA_PUBLIC_URL", "https://lyraauth.com").rstrip("/")


def _apple_key() -> str:
    key = os.getenv("APPLE_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    if not key and os.getenv("APPLE_PRIVATE_KEY_FILE"):
        try:
            with open(os.environ["APPLE_PRIVATE_KEY_FILE"]) as f:
                key = f.read().strip()
        except OSError:
            key = ""
    return key


def configured(name: str) -> bool:
    p = PROVIDERS.get(name)
    if not p or not all(os.getenv(v) for v in p["env"]):
        return False
    return bool(_apple_key()) if name == "apple" else True


def _redirect_uri(name: str) -> str:
    return f"{public_url()}/api/oauth/{name}/callback"


def _safe_next(value: Optional[str]) -> str:
    if (not value or not value.startswith("/") or value.startswith("//") or "\\" in value
            or len(value) > 300 or not set(value) <= SAFE_NEXT_CHARS):
        return "/"
    return value


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _back(error: str, provider: str = "", link: bool = False) -> RedirectResponse:
    """Back to the sign-in page (or Account, when connecting) with a reason it can show."""
    q = urlencode({"error": error, **({"provider": provider} if provider else {})})
    r = RedirectResponse(f"{ACCOUNT if link else LOGIN}?{q}", status_code=303)
    r.delete_cookie(STATE_COOKIE, path="/api/oauth", secure=sessions._secure(), samesite="none" if sessions._secure() else "lax")
    r.headers["Cache-Control"] = "no-store"
    return r


def _set_state(response, payload: dict) -> None:
    token = jwt.encode({**payload, "exp": int(time.time()) + STATE_TTL, "aud": "lyra-oauth"}, SECRET_KEY, algorithm="HS256")
    # Apple returns with a cross-site form POST, which a SameSite=Lax cookie wouldn't ride on.
    # The cookie is signed, short-lived and only names this one sign-in attempt.
    secure = sessions._secure()
    response.set_cookie(STATE_COOKIE, token, max_age=STATE_TTL, httponly=True, secure=secure,
                        samesite="none" if secure else "lax", path="/api/oauth")


def _read_state(request: Request) -> Optional[dict]:
    raw = request.cookies.get(STATE_COOKIE)
    if not raw or len(raw) > 2000:
        return None
    try:
        return jwt.decode(raw, SECRET_KEY, algorithms=["HS256"], audience="lyra-oauth")
    except jwt.PyJWTError:
        return None


def _apple_client_secret() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": os.environ["APPLE_TEAM_ID"], "iat": now, "exp": now + 300,
         "aud": "https://appleid.apple.com", "sub": os.environ["APPLE_CLIENT_ID"]},
        _apple_key(), algorithm="ES256", headers={"kid": os.environ["APPLE_KEY_ID"]})


def _client_secret(name: str) -> str:
    return _apple_client_secret() if name == "apple" else os.environ[PROVIDERS[name]["env"][1]]


def _id_claims(name: str, id_token: str, nonce: str) -> dict:
    """Claims of an ID token received directly from the provider's token endpoint over TLS.
    OpenID Connect allows trusting the TLS connection instead of the signature here; every
    claim that ties the token to this sign-in is still checked."""
    claims = jwt.decode(id_token, options={"verify_signature": False})
    p = PROVIDERS[name]
    if claims.get("iss") not in p["issuers"]:
        raise ValueError("issuer")
    aud = claims.get("aud")
    if os.environ[p["env"][0]] not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("audience")
    if int(claims.get("exp", 0)) < time.time() - 60:
        raise ValueError("expired")
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("nonce")
    return claims


def _verified(value) -> bool:
    return value is True or str(value).lower() == "true"


def _profile(name: str, code: str, state: dict, form_user: str = "") -> dict:
    """Swap the code for tokens and return {subject, email, name}. Email is "" unless verified."""
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(name),
            "client_id": os.environ[PROVIDERS[name]["env"][0]], "client_secret": _client_secret(name)}
    if name != "apple":
        data["code_verifier"] = state["v"]
    with http_client() as client:
        r = client.post(PROVIDERS[name]["token"], data=data, headers={"Accept": "application/json"})
        r.raise_for_status()
        tokens = r.json()
        if "error" in tokens:
            raise ValueError(tokens["error"])
        if name == "github":
            auth = {"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/vnd.github+json"}
            me = client.get("https://api.github.com/user", headers=auth).json()
            emails = client.get("https://api.github.com/user/emails", headers=auth).json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None) \
                or next((e for e in emails if e.get("verified")), None)
            return {"subject": str(me["id"]), "email": (primary or {}).get("email", ""),
                    "name": me.get("name") or me.get("login") or ""}
    claims = _id_claims(name, tokens["id_token"], state["n"])
    full = claims.get("name", "")
    if name == "apple" and form_user:
        # Apple sends the person's name once, on their first sign-in, outside the token.
        try:
            n = json.loads(form_user).get("name") or {}
            full = " ".join(x for x in (n.get("firstName"), n.get("lastName")) if x)
        except (ValueError, AttributeError):
            pass
    return {"subject": str(claims["sub"]), "email": claims.get("email", "") if _verified(claims.get("email_verified")) else "",
            "name": full}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/providers")
def providers():
    return {name: configured(name) for name in PROVIDERS}


@router.get("/{name}/start")
def start(name: str, request: Request, next: str = "/", link: int = 0, db: Session = Depends(get_db)):
    if name not in PROVIDERS:
        raise HTTPException(404, "No such provider")
    ratelimit.check(f"oauth-start:{ratelimit.client_ip(request)}", limit=30, window=600)
    linking = None
    if link:
        user = sessions.user_from_cookie(request, db)
        if not user:
            return _back("signin_first", name)
        linking = user.id
    elif sessions.user_from_cookie(request, db):
        return RedirectResponse(_safe_next(next), status_code=303)
    if not configured(name):
        return _back("unavailable", name, bool(link))

    state, verifier, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    p = PROVIDERS[name]
    params = {"client_id": os.environ[p["env"][0]], "redirect_uri": _redirect_uri(name), "response_type": "code",
              "scope": p["scope"], "state": state}
    if name == "apple":
        params.update(response_mode="form_post", nonce=nonce)
    else:
        params.update(code_challenge=_b64(hashlib.sha256(verifier.encode()).digest()), code_challenge_method="S256")
    if name == "google":
        params.update(nonce=nonce, prompt="select_account")
    if name == "github":
        params["allow_signup"] = "true"

    r = RedirectResponse(f"{p['authorize']}?{urlencode(params)}", status_code=303)
    _set_state(r, {"p": name, "s": state, "v": verifier, "n": nonce, "next": _safe_next(next), "link": linking})
    r.headers["Cache-Control"] = "no-store"
    return r


@router.api_route("/{name}/callback", methods=["GET", "POST"])
async def callback(name: str, request: Request, db: Session = Depends(get_db)):
    if name not in PROVIDERS:
        raise HTTPException(404, "No such provider")
    params = dict(request.query_params)
    if request.method == "POST":
        params.update({k: v for k, v in (await request.form()).items() if isinstance(v, str)})
    state = _read_state(request)
    link = bool(state and state.get("link"))
    if params.get("error"):
        cancelled = params["error"] in ("access_denied", "user_cancelled_authorize", "user_cancelled_login")
        return _back("cancelled" if cancelled else "provider_error", name, link)
    if (not state or state.get("p") != name or not params.get("state") or not params.get("code")
            or not secrets.compare_digest(str(state.get("s")), params["state"])):
        return _back("expired", name, link)
    if not configured(name):
        return _back("unavailable", name, link)

    try:
        profile = _profile(name, params["code"], state, params.get("user", ""))
    except Exception:  # noqa: BLE001 — any failure talking to the provider is the same to the visitor
        return _back("provider_error", name, link)

    identity = db.query(OAuthIdentity).filter(OAuthIdentity.provider == name,
                                              OAuthIdentity.subject == profile["subject"]).first()
    if link:
        user = db.query(User).filter(User.id == state["link"], User.is_active == True).first()  # noqa: E712
        if not user:
            return _back("signin_first", name)
        if identity and identity.user_id != user.id:
            return _back("linked_elsewhere", name, True)
        if not identity:
            db.add(OAuthIdentity(user_id=user.id, provider=name, subject=profile["subject"], email=profile["email"]))
            db.commit()
        r = RedirectResponse(f"{ACCOUNT}?connected={name}", status_code=303)
        r.delete_cookie(STATE_COOKIE, path="/api/oauth")
        return r

    if identity:
        user = db.query(User).filter(User.id == identity.user_id).first()
        if not user or not user.is_active:
            return _back("disabled", name)
    else:
        email = profile["email"].lower().strip()
        if not email or len(email) > 254:
            return _back("no_email", name)
        user = db.query(User).filter(User.email == email).first()
        if user and has_password(user):
            return _back("link_required", name)
        if user and not user.is_active:
            return _back("disabled", name)
        if not user:
            user = User(email=email, password_hash=NO_PASSWORD, name=(profile["name"] or email.split("@")[0])[:80])
            db.add(user)
            db.flush()
        db.add(OAuthIdentity(user_id=user.id, provider=name, subject=profile["subject"], email=email))
        db.commit()

    r = RedirectResponse(state.get("next") or "/", status_code=303)
    r.delete_cookie(STATE_COOKIE, path="/api/oauth")
    r.headers["Cache-Control"] = "no-store"
    sessions.start(db, user, request, r)
    return r


@router.get("/identities")
def identities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(OAuthIdentity).filter(OAuthIdentity.user_id == user.id).order_by(OAuthIdentity.created_at).all()
    return {"has_password": has_password(user),
            "connected": [{"provider": r.provider, "email": r.email, "created_at": r.created_at} for r in rows],
            "available": providers()}


@router.delete("/{name}")
def disconnect(name: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(OAuthIdentity).filter(OAuthIdentity.user_id == user.id).all()
    mine = [r for r in rows if r.provider == name]
    if not mine:
        raise HTTPException(404, "That account isn't connected")
    if not has_password(user) and len(rows) == len(mine):
        raise HTTPException(400, "Set a password first: this is the only way you can sign in")
    for r in mine:
        db.delete(r)
    db.commit()
    return {"ok": True}
