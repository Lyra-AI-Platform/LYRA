"""Plan limits and names in one place, with no web or database imports, so the sites API,
LyraAuth, the billing page and the tests can't disagree.

Free is a real plan: it never expires. New accounts also get a 14-day trial of the paid
products on top of it (lyra/api/entitlements.py).
"""
from typing import Dict, Optional, Tuple

# tier: (LyraAuth verifications a month across the account, active sites). None = no limit.
SITE_LIMITS: Dict[str, Tuple[Optional[int], Optional[int]]] = {
    "free": (10_000, 1),
    "starter": (100_000, 10),
    "pro": (500_000, None),
    "business": (2_000_000, None),
    "enterprise": (None, None),
}

PLAN_NAMES = {
    "free": "Free",
    "starter": "Starter",
    "pro": "Pro",
    "business": "Business",
    "enterprise": "Enterprise",
    "markets": "Markets Pro",
    "bundle": "Markets Pro + Watch Pro",
}


def site_limits(tier: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Markets Pro and the bundle aren't LyraAuth plans, so they get the Free allowance."""
    return SITE_LIMITS.get(tier or "free", SITE_LIMITS["free"])


def plan_name(tier: Optional[str]) -> str:
    return PLAN_NAMES.get(tier or "free", PLAN_NAMES["free"])


def over_monthly_limit(tier: Optional[str], used: int) -> bool:
    limit = site_limits(tier)[0]
    return limit is not None and used >= limit


def can_add_site(tier: Optional[str], active_sites: int) -> bool:
    limit = site_limits(tier)[1]
    return limit is None or active_sites < limit
