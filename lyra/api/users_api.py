"""
User authentication API.
POST /api/users/register  — create account, returns JWT
POST /api/users/login     — email+password, returns JWT
GET  /api/users/me        — current user profile (requires auth)
PUT  /api/users/me        — update name
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from lyra.db.database import get_db
from lyra.db.models import User

router = APIRouter(prefix="/api/users", tags=["users"])

# ── JWT config ────────────────────────────────────────────────────────────────
SECRET_KEY  = os.getenv("JWT_SECRET", "change-me-in-production-use-a-long-random-string")
ALGORITHM   = "HS256"
TOKEN_HOURS = 24 * 7  # 7-day tokens

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

@router.post("/register", status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if db.query(User).filter(User.email == req.email.lower()).first():
        raise HTTPException(400, "Email already registered")

    user = User(
        email=req.email.lower().strip(),
        password_hash=_hash_password(req.password),
        name=req.name.strip() or req.email.split("@")[0],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"token": _create_token(user.id), "user": UserOut.model_validate(user)}


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower()).first()
    if not user or not _verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")

    return {"token": _create_token(user.id), "user": UserOut.model_validate(user)}


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
        user.name = req.name.strip()
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
