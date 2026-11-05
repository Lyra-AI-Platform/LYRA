"""Part 8: what each plan may do is decided on the server."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-plans-test-"))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from lyra.api import entitlements as ent  # noqa: E402
from lyra.db.models import Base, User  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def user(db, tier="free", days_old=400):
    u = User(email=f"{tier}{days_old}@example.com", password_hash="x", tier=tier,
             created_at=datetime.now(timezone.utc) - timedelta(days=days_old))
    db.add(u)
    db.commit()
    return u


def test_free_gets_one_reading_a_day(db):
    u = user(db)
    ent.check(u, "market", db, consume=1)
    with pytest.raises(HTTPException) as e:
        ent.check(u, "market", db, consume=1)
    assert e.value.status_code == 402 and e.value.detail["reason"] == "daily_allowance_used"


def test_the_allowance_comes_back_the_next_day(db):
    u = user(db)
    ent.check(u, "market", db, consume=1)
    row = ent._usage(u, "market_day", db)
    row.last_used = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    ent.check(u, "market", db, consume=1)


@pytest.mark.parametrize("tier", ["markets", "bundle", "starter"])
def test_paid_plans_are_unlimited(db, tier):
    u = user(db, tier)
    for _ in range(10):
        ent.check(u, "market", db, consume=1)


def test_markets_pro_does_not_unlock_chat(db):
    with pytest.raises(HTTPException):
        ent.check(user(db, "markets"), "chat", db, consume=1)


def test_timeline_is_gated(db):
    dep = ent.require_markets("timeline")
    with pytest.raises(HTTPException):
        dep(user(db))
    assert dep(user(db, "markets")).tier == "markets"
