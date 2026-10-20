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

from lyra.api import ratelimit
from lyra.db.database import get_db
from lyra.db.models import User

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


SECRET_KEY  = _load_secret()
ALGORITHM   = "HS256"
TOKEN_HOURS = 24 * 7  # 7-day tokens

# Pages are guarded on the server (lyra/api/page_access.py), so a sign-in also sets this
# cookie. It is HttpOnly (scripts can't read it) and only ever accepted for GETs of pages
# and read-only data, never for actions, so it can't be used for cross-site request forgery.
# LYRA_IN is a plain marker the page scripts can see, telling them the cookie exists.
SESSION_COOKIE = "lyra_session"
MARKER_COOKIE  = "lyra_in"

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer   = HTTPBearer(auto_error=False)


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""

class LoginRequest(BaseModel):
    email: str
    password: str

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
    return pwd_ctx.verify(plain, hashed)

def _create_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def set_session(response: Response, token: str) -> None:
    secure = os.getenv("LYRA_INSECURE_COOKIES") != "1"   # plain-http local testing only
    age = TOKEN_HOURS * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=age, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(MARKER_COOKIE, "1", max_age=age, httponly=False, secure=secure, samesite="lax", path="/")


def clear_session(response: Response) -> None:
    for name in (SESSION_COOKIE, MARKER_COOKIE):
        response.delete_cookie(name, path="/")


def user_from_cookie(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        user_id = int(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: decode JWT and return the User row."""
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


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
    if not 8 <= len(req.password) <= 128:
        raise HTTPException(400, "Password must be 8 to 128 characters")
    if len(req.name) > 80:
        raise HTTPException(400, "Name is too long")
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

    token = _create_token(user.id)
    set_session(response, token)
    return {"token": token, "user": UserOut.model_validate(user)}


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = req.email.lower().strip()[:254]
    ip_key, email_key = f"login-ip:{ratelimit.client_ip(request)}", f"login-email:{email}"
    # Failed attempts only: 20 per address and 10 per account in 15 minutes.
    ratelimit.check(ip_key, limit=20, window=900, record=False)
    ratelimit.check(email_key, limit=10, window=900, record=False)
    user = db.query(User).filter(User.email == email).first()
    if not user or len(req.password) > 128 or not _verify_password(req.password, user.password_hash):
        ratelimit.record(ip_key)
        ratelimit.record(email_key)
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")

    token = _create_token(user.id)
    set_session(response, token)
    return {"token": token, "user": UserOut.model_validate(user)}


@router.post("/session")
def session(response: Response, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
            user: User = Depends(get_current_user)):
    """Turn a sign-in held by the page (bearer token) into the page cookie. For accounts that
    signed in before the cookie existed; the token keeps its own expiry."""
    set_session(response, creds.credentials)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    clear_session(response)
    return {"ok": True}


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
