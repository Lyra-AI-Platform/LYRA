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
    upgrade(engine)


# Columns added after a table first shipped: create_all never alters an existing table.
NEW_COLUMNS = (("sites", "secret_hint", "VARCHAR DEFAULT ''"),
               ("verified_tokens", "hostname", "VARCHAR DEFAULT ''"),
               ("verified_tokens", "score", "FLOAT DEFAULT 0"))


def upgrade(bind) -> None:
    """Bring an existing database up to date. Safe to run on every start."""
    from sqlalchemy import inspect, text
    from lyra.authenticator.guard import hash_secret, is_hashed
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table, column, kind in NEW_COLUMNS:
            if inspector.has_table(table) and column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {kind}"))
        # Keys stored before hashing: customers keep using the same key, only the copy here changes.
        for row in conn.execute(text("SELECT id, secret_key FROM sites")).fetchall():
            if not is_hashed(row[1]):
                conn.execute(text("UPDATE sites SET secret_key=:h, secret_hint=:t WHERE id=:i"),
                             {"h": hash_secret(row[1]), "t": row[1][-4:], "i": row[0]})
