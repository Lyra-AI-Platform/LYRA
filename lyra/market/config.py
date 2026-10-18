"""Market expert configuration. Everything here can be overridden with env vars
or by editing the JSON files in data/market/."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.environ.get("LYRA_MARKET_DIR", ROOT / "data" / "market"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "market.db"
PEERS_FILE = DATA_DIR / "peers.json"
NOTABLE_TRADES_FILE = DATA_DIR / "notable_trades.json"

# The SEC asks every client to identify itself with a contact address.
SEC_USER_AGENT = os.environ.get("LYRA_SEC_USER_AGENT", "Lyra Market Expert lyra@example.com")
BROWSER_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Name of the index. Each ticker's reading is labelled "TRX-<TICKER>".
INDEX_NAME = "Tremor Index"
INDEX_CODE = "TRX"

# A prediction is graded after this many calendar days.
HORIZON_DAYS = int(os.environ.get("LYRA_MARKET_HORIZON_DAYS", 30))
# Move (as a fraction) that counts as a boom or a bust over the horizon.
BOOM_THRESHOLD = float(os.environ.get("LYRA_MARKET_BOOM", 0.05))
BUST_THRESHOLD = float(os.environ.get("LYRA_MARKET_BUST", 0.05))
# Never suggest putting more than this fraction of a portfolio into one name.
MAX_POSITION = float(os.environ.get("LYRA_MARKET_MAX_POSITION", 0.05))

LOOKBACK_DAYS_INSIDERS = 90
LOOKBACK_DAYS_CONGRESS = 90

# Famous 13F filers whose holdings are checked for every ticker.
# weight = how much the market tends to follow them.
NOTABLE_FUNDS = [
    {"name": "Berkshire Hathaway (Warren Buffett)", "cik": "0001067983", "weight": 1.0},
    {"name": "Pershing Square (Bill Ackman)", "cik": "0001336528", "weight": 0.8},
    {"name": "Scion Asset Management (Michael Burry)", "cik": "0001649339", "weight": 0.8},
    {"name": "Bridgewater Associates (Ray Dalio)", "cik": "0001350694", "weight": 0.7},
    {"name": "ARK Investment Management (Cathie Wood)", "cik": "0001697748", "weight": 0.6},
    {"name": "Renaissance Technologies", "cik": "0001037389", "weight": 0.7},
    {"name": "Duquesne Family Office (Stanley Druckenmiller)", "cik": "0001536411", "weight": 0.8},
    {"name": "Appaloosa (David Tepper)", "cik": "0001656456", "weight": 0.7},
]

# How informative a trade is depending on who makes it.
ROLE_WEIGHTS = {
    "ceo": 1.0, "chief executive": 1.0, "founder": 1.0, "chairman": 0.9,
    "cfo": 0.9, "chief financial": 0.9, "president": 0.85, "coo": 0.85,
    "cto": 0.8, "chief technology": 0.8, "officer": 0.7, "director": 0.6,
    "10% owner": 0.5, "politician": 0.7,
}
# Open-market purchases say far more than sales (sales are often scheduled
# 10b5-1 plans, tax or diversification), so sales count for less.
SELL_DISCOUNT = 0.4

CONGRESS_SOURCES = [
    {"chamber": "house", "url": os.environ.get(
        "LYRA_HOUSE_TRADES_URL",
        "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json")},
    {"chamber": "senate", "url": os.environ.get(
        "LYRA_SENATE_TRADES_URL",
        "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json")},
]

# News feeds. {t} is replaced with the ticker, {q} with a search query.
TICKER_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US",
    "https://news.google.com/rss/search?q={q}+stock&hl=en-US&gl=US&ceid=US:en",
]
MARKET_FEEDS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://news.google.com/rss/search?q=stock+market+VIX&hl=en-US&gl=US&ceid=US:en",
]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def load_peers():
    """Peers are other Lyra nodes or JSON signal files published on GitHub.
    Format: [{"name": "...", "url": "...", "type": "lyra"|"json", "weight": 1.0}]"""
    return load_json(PEERS_FILE, [])


def load_notable_trades():
    """Hand-curated trades by people the HTTP sources don't cover
    (e.g. a tech leader's publicly reported buy). Format:
    [{"ticker": "NVDA", "person": "...", "role": "ceo", "side": "buy",
      "value": 1000000, "date": "2026-09-30", "source": "url"}]"""
    return load_json(NOTABLE_TRADES_FILE, [])
