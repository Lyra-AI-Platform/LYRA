"""Trial and paywall rules (lyra/api/entitlements.py), on a throwaway SQLite database."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-ent-test-"))

from lyra.db.models import Base, User  # noqa: E402
from lyra.api import entitlements as ent  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, tier="free", days_old=0):
    u = User(email=f"{tier}{days_old}@example.com", password_hash="x", tier=tier,
             created_at=datetime.now(timezone.utc) - timedelta(days=days_old))
    db.add(u)
    db.commit()
    return u


def test_trial_allowance_then_402(db):
    u = _user(db)
    for _ in range(ent.TRIAL_LIMITS["market"]):
        ent.check(u, "market", db, consume=1)
    with pytest.raises(HTTPException) as e:
        ent.check(u, "market", db, consume=1)
    assert e.value.status_code == 402
    assert e.value.detail["upgrade_url"] == ent.UPGRADE_URL
    # reading (no consume) is still allowed while the trial window is open
    ent.check(u, "market", db)
    # a different feature has its own allowance
    ent.check(u, "chat", db, consume=1)


def test_trial_expires_by_time(db):
    u = _user(db, days_old=ent.TRIAL_DAYS + 1)
    with pytest.raises(HTTPException) as e:
        ent.check(u, "chat", db)
    assert e.value.detail["reason"] == "trial_expired"
    assert ent.status(u, db)["trial"]["expired"]


def test_paid_users_are_never_limited(db):
    for tier in ent.PAID_TIERS:
        u = _user(db, tier=tier, days_old=400)
        for _ in range(ent.TRIAL_LIMITS["market"] + 5):
            ent.check(u, "market", db, consume=1)
        assert ent.status(u, db)["paid"] and ent.status(u, db)["trial"] is None


def test_status_reports_remaining(db):
    u = _user(db)
    ent.check(u, "chat", db, consume=5)
    s = ent.status(u, db)
    assert s["trial"]["remaining"]["chat"] == ent.TRIAL_LIMITS["chat"] - 5
    assert s["trial"]["days_left"] == ent.TRIAL_DAYS or s["trial"]["days_left"] == ent.TRIAL_DAYS - 1
