"""
SQLAlchemy ORM models for LyraAuth SaaS.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from lyra.db.database import Base


def _now():
    return datetime.now(timezone.utc)


def _site_key():
    return "lyra_sk_" + secrets.token_urlsafe(24)


def _secret_key():
    return "lyra_secret_" + secrets.token_urlsafe(32)


class User(Base):
    __tablename__ = "users"

    id                   = Column(Integer, primary_key=True, index=True)
    email                = Column(String, unique=True, nullable=False, index=True)
    password_hash        = Column(String, nullable=False)
    name                 = Column(String, default="")
    tier                 = Column(String, default="free")          # free | pro | enterprise
    stripe_customer_id   = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    is_active            = Column(Boolean, default=True)
    created_at           = Column(DateTime(timezone=True), default=_now)

    sites = relationship("Site", back_populates="owner", cascade="all, delete-orphan")


class TrialUsage(Base):
    """How much of each trial allowance an unpaid account has used (see lyra/api/entitlements.py)."""
    __tablename__ = "trial_usage"

    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    feature   = Column(String, nullable=False)        # market | chat
    count     = Column(Integer, default=0)
    last_used = Column(DateTime(timezone=True), nullable=True)


class Site(Base):
    """One row per website registered by a user."""
    __tablename__ = "sites"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    name       = Column(String, default="My Site")
    domain     = Column(String, default="")
    site_key   = Column(String, unique=True, nullable=False, default=_site_key, index=True)
    secret_key = Column(String, unique=True, nullable=False, default=_secret_key, index=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    owner  = relationship("User", back_populates="sites")
    tokens = relationship("VerifiedToken", back_populates="site", cascade="all, delete-orphan")
    usage  = relationship("UsageRecord", back_populates="site", cascade="all, delete-orphan")


class VerifiedToken(Base):
    """
    One-use tokens issued by /api/auth/verify (widget → backend).
    Consumed by /api/auth/siteverify (backend → LyraAuth).
    Prevents replay attacks.
    """
    __tablename__ = "verified_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    token      = Column(String, unique=True, nullable=False, index=True)
    site_id    = Column(Integer, ForeignKey("sites.id"), nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)  # 5-min TTL

    site = relationship("Site", back_populates="tokens")


class UsageRecord(Base):
    """Daily verification count per site (for tier limits and billing)."""
    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("site_id", "date", name="uq_site_date"),)

    id      = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    date    = Column(String, nullable=False)   # ISO date string YYYY-MM-DD
    count   = Column(Integer, default=0)

    site = relationship("Site", back_populates="usage")


# ── Lyra Watch: its own subscription, AI credits and sponsors ─────────────

class WatchSubscription(Base):
    """Lyra Watch Pro, a Stripe subscription separate from the main plans."""
    __tablename__ = "watch_subscriptions"

    id                     = Column(Integer, primary_key=True)
    user_id                = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    status                 = Column(String, default="inactive")   # active | trialing | past_due | canceled ...
    updated_at             = Column(DateTime(timezone=True), default=_now, onupdate=_now)


def _api_key():
    return "lw_" + secrets.token_urlsafe(32)


class CreditWallet(Base):
    """Prepaid credits that API keys spend (AI agents pay per request)."""
    __tablename__ = "credit_wallets"

    id      = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    balance = Column(Integer, default=0)
    spent   = Column(Integer, default=0)


class ApiKey(Base):
    """Only a hash of the key is stored; the key itself is shown once, when it's made."""
    __tablename__ = "api_keys"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name       = Column(String, default="")
    prefix     = Column(String, nullable=False)          # first characters, to tell keys apart
    key_hash   = Column(String, unique=True, nullable=False, index=True)
    is_active  = Column(Boolean, default=True)
    requests   = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_now)
    last_used  = Column(DateTime(timezone=True), nullable=True)


class LoginSession(Base):
    """One signed-in browser. The cookie holds a random ID; only its hash is stored, so a
    copy of the database can't be used to sign in. Deleting the row signs that browser out."""
    __tablename__ = "login_sessions"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    last_seen  = Column(DateTime(timezone=True), default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    ip         = Column(String, default="")
    user_agent = Column(String, default="")


class OAuthIdentity(Base):
    """A Google, Apple or GitHub account that signs in as `user_id` (lyra/api/oauth_api.py).
    `subject` is the provider's stable ID for the person; the email can change, it can't."""
    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),)

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider   = Column(String, nullable=False)        # google | apple | github
    subject    = Column(String, nullable=False)
    email      = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=_now)


class LabsConnection(Base):
    """An AI a user plugged into Lyra Labs (lyra/labs/llm.py). The key is encrypted at rest."""
    __tablename__ = "labs_connections"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name       = Column(String, default="My AI")
    kind       = Column(String, nullable=False)          # anthropic | openai
    base_url   = Column(String, default="")
    model      = Column(String, default="")
    key_sealed = Column(Text, nullable=False)
    key_hint   = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=_now)


class Feedback(Base):
    """A message sent from /feedback/ (lyra/api/feedback_api.py). Kept even if emailing it fails."""
    __tablename__ = "feedback"

    id         = Column(Integer, primary_key=True)
    kind       = Column(String, default="other")
    message    = Column(Text, nullable=False)
    email      = Column(String, default="")
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    rating     = Column(Integer, nullable=True)
    page       = Column(String, default="")
    ip         = Column(String, default="")
    user_agent = Column(String, default="")
    emailed    = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)


class CreditPurchase(Base):
    """One row per paid Stripe checkout, so a repeated webhook never adds credits twice."""
    __tablename__ = "credit_purchases"

    id                = Column(Integer, primary_key=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    stripe_session_id = Column(String, unique=True, nullable=False)
    credits           = Column(Integer, nullable=False)
    amount_cents      = Column(Integer, nullable=False)
    created_at        = Column(DateTime(timezone=True), default=_now)


class Sponsor(Base):
    """A paid sponsor slot on Lyra Watch. Shown only after payment and the owner's approval."""
    __tablename__ = "sponsors"

    id                = Column(Integer, primary_key=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    headline          = Column(String, nullable=False)
    body              = Column(String, default="")
    url               = Column(String, nullable=False)
    weeks             = Column(Integer, default=1)
    status            = Column(String, default="unpaid")   # unpaid | paid | live | rejected
    stripe_session_id = Column(String, nullable=True, index=True)
    impressions       = Column(Integer, default=0)
    clicks            = Column(Integer, default=0)
    created_at        = Column(DateTime(timezone=True), default=_now)
    starts_at         = Column(DateTime(timezone=True), nullable=True)
    ends_at           = Column(DateTime(timezone=True), nullable=True)
