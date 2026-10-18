"""Watchlist configuration. The roster ships with the code; an operator copy in
data/watch/roster.json (same format) replaces it when present."""
import os
from pathlib import Path

from lyra.market.config import DATA_DIR as MARKET_DIR, load_json

WATCH_DIR = Path(os.environ.get("LYRA_WATCH_DIR", MARKET_DIR.parent / "watch"))
WATCH_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR = WATCH_DIR / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)
SEED_ROSTER = Path(__file__).parent / "roster.json"

# Disclosed trades from the last this-many days are collected; headlines and posts
# from a shorter window, since coverage goes stale much faster than filings.
LOOKBACK_DAYS = int(os.environ.get("LYRA_WATCH_LOOKBACK_DAYS", 365))
STATEMENT_DAYS = int(os.environ.get("LYRA_WATCH_STATEMENT_DAYS", 30))
# How often every profile is rebuilt in the background.
REFRESH_HOURS = float(os.environ.get("LYRA_WATCH_REFRESH_HOURS", 6))
CATEGORIES = {"politician": "Politicians", "investor": "Investors & traders",
              "executive": "Executives", "public-figure": "Public figures"}


def load_roster():
    """[{slug, name, category, country, role, affiliation?, sec_cik?, fund_cik?, house?, news_query, feeds?}]"""
    roster = load_json(WATCH_DIR / "roster.json", None) or load_json(SEED_ROSTER, [])
    return [p for p in roster if p.get("slug") and p.get("name")]
