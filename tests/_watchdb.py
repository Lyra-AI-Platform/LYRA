"""Shared by the Lyra Watch API tests: an app on a throwaway database, and signed-in users."""
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from lyra.api import sessions
from lyra.db.database import get_db
from lyra.db.models import Base, LoginSession, User


def make_app(*routers):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = FastAPI()
    for r in routers:
        app.include_router(r)

    def db():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = db
    return app, Session


def signed_in(Session, tier="free", email=None):
    """A user row and the Authorization header that signs them in."""
    s = Session()
    u = User(email=email or f"{tier}-{id(s)}@example.com", password_hash="x", tier=tier)
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return uid, {"Cookie": f"{sessions.COOKIE}={session_token(Session, uid)}"}


def session_token(Session, user_id):
    """A live sign-in for user_id: the value of the session cookie."""
    token, now = secrets.token_urlsafe(32), datetime.now(timezone.utc)
    s = Session()
    s.add(LoginSession(user_id=user_id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                       created_at=now, last_seen=now, expires_at=now + timedelta(days=30)))
    s.commit()
    s.close()
    return token
