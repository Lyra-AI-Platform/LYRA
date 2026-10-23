"""
User authentication API.
POST /api/users/register  — create account, returns JWT
POST /api/users/login     — email+password, returns JWT
GET  /api/users/me        — current user profile (requires auth)
PUT  /api/users/me        — update name
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
try:  # PyJWT; python-jose (unmaintained, pulls in a vulnerable ecdsa) only where PyJWT isn't installed yet
    import jwt
    from jwt import PyJWTError as JWTError
except ImportError:
    from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from lyra.api import ratelimit, sessions
from lyra.db.database import get_db
from lyra.db.models import LoginSession, User

router = APIRouter(prefix="/api/users", tags=["users"])

# ── JWT config ────────────────────────────────────────────────────────────────
def _load_secret() -> str:
    """Use JWT_SECRET if set; otherwise generate a random one once and keep it in
    data/, so tokens can't be forged with a default key published in the source."""
    if os.getenv("JWT_SECRET"):
        return os.environ["JWT_SECRET"]
    path = Path(__file__).parent.parent.parent / "data" / ".jwt_secret"
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(48)
        path.write_text(secret)
        path.chmod(0o600)
        return secret


# Sign-in is a server-side session in an HttpOnly cookie (lyra/api/sessions.py). The old site
# handed out 7-day JWTs that pages kept in localStorage; those are only accepted once more, by
# POST /session, to move a browser that still holds one onto a session.
SECRET_KEY  = _load_secret()
ALGORITHM   = "HS256"
SESSION_COOKIE = sessions.COOKIE

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer   = HTTPBearer(auto_error=False)


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    website: str = ""      # hidden from people; only form-filling bots put anything here

class LoginRequest(BaseModel):
    email: str
    password: str

class PasswordChange(BaseModel):
    current_password: str = ""     # not needed by an account that has no password yet
    new_password: str

class UpdateMeRequest(BaseModel):
    name: Optional[str] = None

class UserOut(BaseModel):
    id: int
    email: str
    name: str
    tier: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(plain, hashed)
    except ValueError:   # NO_PASSWORD, or anything else that isn't a password hash
        return False


# Accounts made by signing in with Google, Apple or GitHub (oauth_api.py) have no password
# until they set one; nothing can match this value.
NO_PASSWORD = "!no-password"


def has_password(user: User) -> bool:
    return bool(user.password_hash) and user.password_hash != NO_PASSWORD

# Checked against when an email has no account, so a wrong email takes as long as a wrong
# password and the response time doesn't reveal who has an account.
_NO_ACCOUNT_HASH = pwd_ctx.hash(secrets.token_urlsafe(16))

COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "password1234", "passw0rd", "qwerty",
    "qwerty123", "qwertyuiop", "letmein", "iloveyou", "welcome1", "welcome123", "admin123",
    "abc12345", "abcdefgh", "abcd1234", "1q2w3e4r5t", "1qaz2wsx", "zaq12wsx", "football",
    "baseball", "sunshine", "princess", "dragon123", "monkey123", "trustno1", "superman",
    "123456789", "1234567890", "0987654321", "11111111", "12341234", "87654321",
    "lyraauth", "lyraauth123", "changeme", "default1", "whatever",
}


def password_problem(password: str, email: str = "") -> Optional[str]:
    """Why a new password isn't good enough, or None."""
    if len(password) < 10:
        return "Use at least 10 characters"
    if len(password.encode()) > 72:
        return "That password is too long (72 characters at most)"
    low = password.lower()
    if low in COMMON_PASSWORDS or len(set(low)) < 4:
        return "That password is too easy to guess. Try a few unrelated words"
    name = email.split("@")[0].lower()
    if len(name) >= 4 and name in low:
        return "Don't put your email address in your password"
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """FastAPI dependency: the signed-in user, or 401. Anything that changes something must
    also come from this site's own pages (sessions.same_origin), or it's refused with 403."""
    user = sessions.user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    if request.method not in sessions.SAFE_METHODS and not sessions.same_origin(request):
        raise HTTPException(status_code=403, detail="Refused: this request didn't come from lyraauth.com")
    return user


def _user_from_old_token(token: str, db: Session) -> Optional[User]:
    try:
        user_id = int(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712


# ── Routes ────────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")


def _admin_emails():
    return {e.strip().lower() for e in os.getenv("LYRA_ADMIN_EMAILS", "").split(",") if e.strip()}


@router.post("/register", status_code=201)
def register(req: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ratelimit.check(f"register:{ratelimit.client_ip(request)}", limit=5, window=3600)
    email = req.email.lower().strip()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "Enter a valid email address")
    problem = password_problem(req.password, email)
    if problem:
        raise HTTPException(400, problem)
    if len(req.name) > 80:
        raise HTTPException(400, "Name is too long")
    if req.website:
        raise HTTPException(400, "We couldn't create that account")
    # Owner emails carry admin rights, so nobody else may claim one by signing up first.
    if email in _admin_emails() and os.getenv("LYRA_ALLOW_ADMIN_SIGNUP") != "1":
        raise HTTPException(403, "This email can't be registered here")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already registered")

    user = User(
        email=email,
        password_hash=_hash_password(req.password),
        name=req.name.strip() or req.email.split("@")[0],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    sessions.start(db, user, request, response)
    return {"user": UserOut.model_validate(user)}


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = req.email.lower().strip()[:254]
    ip_key, email_key = f"login-ip:{ratelimit.client_ip(request)}", f"login-email:{email}"
    # Failed attempts only: 20 per address and 10 per account in 15 minutes.
    ratelimit.check(ip_key, limit=20, window=900, record=False)
    ratelimit.check(email_key, limit=10, window=900, record=False)
    user = db.query(User).filter(User.email == email).first()
    usable = user and has_password(user)
    ok = len(req.password) <= 128 and _verify_password(req.password, user.password_hash if usable else _NO_ACCOUNT_HASH) and bool(usable)
    if not user or not ok:
        ratelimit.record(ip_key)
        ratelimit.record(email_key)
        raise HTTPException(401, "That email and password don't match an account")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    if pwd_ctx.needs_update(user.password_hash):
        user.password_hash = _hash_password(req.password)

    sessions.start(db, user, request, response)
    return {"user": UserOut.model_validate(user)}


@router.post("/session")
def move_old_sign_in(request: Request, response: Response, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                     db: Session = Depends(get_db)):
    """For browsers signed in by the old site: swap the token it kept in page storage for a
    session. The page deletes the token either way."""
    if not sessions.same_origin(request, strict=True):
        raise HTTPException(403, "Refused: this request didn't come from lyraauth.com")
    user = _user_from_old_token(creds.credentials, db) if creds else None
    if not user:
        raise HTTPException(401, "Not signed in")
    sessions.start(db, user, request, response)
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sessions.end(db, request, response)
    return {"ok": True}


@router.get("/sessions")
def list_sessions(request: Request, db: Session = Depends(get_db)):
    """Every browser signed in to this account, newest first."""
    found = sessions.current(request, db)
    if not found:
        raise HTTPException(401, "Not signed in")
    here, user = found
    rows = (db.query(LoginSession).filter(LoginSession.user_id == user.id)
            .order_by(LoginSession.last_seen.desc()).all())
    return [{"id": r.id, "current": r.id == here.id, "created_at": r.created_at, "last_seen": r.last_seen,
             "ip": r.ip, "user_agent": r.user_agent} for r in rows]


@router.delete("/sessions/{session_id}")
def end_session(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(LoginSession).filter(LoginSession.id == session_id, LoginSession.user_id == user.id).delete()
    db.commit()
    if not n:
        raise HTTPException(404, "No such session")
    return {"ok": True}


@router.post("/sessions/end-others")
def end_other_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    here, _ = sessions.current(request, db)
    return {"ended": sessions.end_all(db, user.id, keep=here.id)}


@router.post("/password")
def change_password(req: PasswordChange, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Needs the current password, unless the account has none yet (made with Google, Apple or
    GitHub). Every other browser is signed out afterwards."""
    ratelimit.check(f"password:{user.id}", limit=5, window=900, record=False)
    if has_password(user) and (len(req.current_password) > 128 or not _verify_password(req.current_password, user.password_hash)):
        ratelimit.record(f"password:{user.id}")
        raise HTTPException(400, "Your current password isn't right")
    problem = password_problem(req.new_password, user.email)
    if problem:
        raise HTTPException(400, problem)
    user.password_hash = _hash_password(req.new_password)
    db.commit()
    here, _ = sessions.current(request, db)
    return {"ok": True, "signed_out_elsewhere": sessions.end_all(db, user.id, keep=here.id)}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.put("/me")
def update_me(
    req: UpdateMeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.name is not None:
        user.name = req.name.strip()[:80]
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
