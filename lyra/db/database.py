"""
Database connection — SQLite via SQLAlchemy.
Database file lives at data/lyra.db (created automatically on first run).
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Allow override via env var for production (e.g. postgresql://...)
_default_db = str(Path(__file__).parent.parent.parent / "data" / "lyra.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_default_db}")

# SQLite needs check_same_thread=False for multi-threaded use
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once on startup."""
    from lyra.db import models  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)
