"""Shared by the Lyra Watch API tests: an app on a throwaway database, and signed-in users."""
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from lyra.api.users_api import _create_token
from lyra.db.database import get_db
from lyra.db.models import Base, User


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
    return uid, {"Authorization": f"Bearer {_create_token(uid)}"}
