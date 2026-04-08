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
