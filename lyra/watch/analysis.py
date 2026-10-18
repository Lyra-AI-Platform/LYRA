"""Reads headlines and posts about a public figure: which companies they're tied to,
which items look like power moves (deals, stakes, policy, lawsuits), which issues
they're associated with and the overall tone.

Everything is keyword rules over public text, so every label can be traced back
to the words that triggered it. Nothing here guesses a person's private beliefs:
political affiliation only ever comes from the sourced roster entry."""
import re
from collections import Counter
from typing import Dict, Iterable, List, Set

from lyra.market import sentiment

# Companies people talk about most, matched by name in headlines. Cashtags ($NVDA)
# are matched separately against the SEC ticker list.
COMPANIES = {
    "Apple": "AAPL", "Microsoft": "MSFT", "NVIDIA": "NVDA", "Nvidia": "NVDA", "Amazon": "AMZN",
    "Alphabet": "GOOGL", "Google": "GOOGL", "Meta Platforms": "META", "Meta": "META", "Facebook": "META", "Instagram": "META",
    "WhatsApp": "META", "Tesla": "TSLA", "SpaceX": "SPCX", "Berkshire Hathaway": "BRK-B", "JPMorgan": "JPM",
    "Goldman Sachs": "GS", "Morgan Stanley": "MS", "Bank of America": "BAC", "Citigroup": "C",
    "Wells Fargo": "WFC", "BlackRock": "BLK", "Mastercard": "MA", "PayPal": "PYPL",
    "Oracle": "ORCL", "Salesforce": "CRM", "Adobe": "ADBE", "Intel": "INTC", "AMD": "AMD",
    "Broadcom": "AVGO", "Qualcomm": "QCOM", "Micron": "MU", "TSMC": "TSM", "Taiwan Semiconductor": "TSM",
    "ASML": "ASML", "Palantir": "PLTR", "Netflix": "NFLX", "Disney": "DIS", "Warner Bros": "WBD",
    "Paramount": "PARA", "Comcast": "CMCSA", "Spotify": "SPOT", "Uber": "UBER", "Airbnb": "ABNB",
    "Coinbase": "COIN", "MicroStrategy": "MSTR", "Strategy Inc": "MSTR", "Robinhood": "HOOD",
    "Boeing": "BA", "Lockheed Martin": "LMT", "Raytheon": "RTX", "RTX": "RTX", "Northrop Grumman": "NOC",
    "General Dynamics": "GD", "Exxon": "XOM", "ExxonMobil": "XOM", "Chevron": "CVX", "BP": "BP", "Occidental": "OXY", "Pfizer": "PFE", "Moderna": "MRNA", "Eli Lilly": "LLY",
    "Novo Nordisk": "NVO", "Johnson & Johnson": "JNJ", "UnitedHealth": "UNH", "Walmart": "WMT",
    "Costco": "COST", "Home Depot": "HD", "Nike": "NKE", "Starbucks": "SBUX",
    "McDonald's": "MCD", "Coca-Cola": "KO", "PepsiCo": "PEP", "Procter & Gamble": "PG",
    "Ford Motor": "F", "General Motors": "GM", "Rivian": "RIVN", "Toyota": "TM", "Stellantis": "STLA",
    "Caterpillar": "CAT", "Deere": "DE", "3M": "MMM", "Honeywell": "HON", "General Electric": "GE",
    "AT&T": "T", "Verizon": "VZ", "T-Mobile": "TMUS", "IBM": "IBM", "Cisco": "CSCO", "Dell": "DELL",
    "Super Micro": "SMCI", "Arm Holdings": "ARM", "Snowflake": "SNOW", "CrowdStrike": "CRWD",
    "Shopify": "SHOP", "Alibaba": "BABA", "Tencent": "TCEHY", "Baidu": "BIDU", "BYD": "BYDDY",
    "Samsung": "005930.KS", "Sony": "SONY", "SoftBank": "SFTBY", "Trump Media": "DJT", "Truth Social": "DJT",
    "Rumble": "RUM", "GameStop": "GME", "AMC": "AMC", "Lululemon": "LULU", "Hershey": "HSY",
    "Saudi Aramco": "2222.SR", "Aramco": "2222.SR", "LVMH": "MC.PA", "Airbus": "AIR.PA",
    "Siemens": "SIE.DE", "Volkswagen": "VOW3.DE", "Rheinmetall": "RHM.DE", "BAE Systems": "BA.L",
    "HSBC": "HSBA.L", "Barclays": "BARC.L", "Reliance Industries": "RELIANCE.NS", "Adani": "ADANIENT.NS",
    "Petrobras": "PBR", "Mercado Libre": "MELI", "YPF": "YPF",
}
# Private companies matter for power moves but have no ticker.
PRIVATE = ["OpenAI", "Anthropic", "xAI", "Neuralink", "The Boring Company", "Blue Origin",
           "Stripe", "Databricks", "ByteDance", "TikTok", "Starlink", "SKIMS", "Roc Nation",
           "Wrexham", "Maximum Effort", "Teremana", "Public Investment Fund", "NEOM", "World Liberty Financial"]

_COMPANY_RE = [(re.compile(rf"(?<![\w&]){re.escape(n)}(?![\w&])"), n, t) for n, t in COMPANIES.items()]
_PRIVATE_RE = [(re.compile(rf"(?<![\w&]){re.escape(n)}(?![\w&])"), n) for n in PRIVATE]
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
_EXCHANGE = re.compile(r"\((?:NYSE|NASDAQ|Nasdaq|LSE|TSX|AMEX)\s*:\s*([A-Z.]{1,6})\)")

# What counts as a power move, and the words that trigger each kind.
MOVE_RULES = [
    ("deal", "Deal / M&A", r"\b(acquir\w*|acquisition|merger|merge|buyout|takeover|bid for|deal|buys? (?:a )?stake)\b"),
    ("investment", "Investment / stake", r"\b(invest\w*|stake|funding round|backs|backed|bets? on|raises? \$|pours?)\b"),
    ("trade", "Trade / position", r"\b(sells? shares|sold shares|dumps?|unloads?|bought shares|buys shares|"
                                   r"share sale|options|call options|put options|short(?:s|ed|ing)? )\b"),
    ("business", "New venture", r"\b(launch\w*|unveil\w*|founds?|founded|starts? (?:a )?(?:company|firm|fund)|new company|spin-?off|ipo)\b"),
    ("policy", "Policy / government", r"\b(executive order|signs?|bill|law|tariffs?|sanctions?|regulat\w*|ban(?:s|ned)?|"
                                       r"veto\w*|decree|budget|summit|treaty)\b"),
    ("contract", "Contract / partnership", r"\b(contract|awarded|partnership|partners? with|agreement|pact|joint venture)\b"),
    ("legal", "Legal", r"\b(lawsuit|sues?|sued|indict\w*|charged|probe|investigat\w*|settle\w*|subpoena\w*|fined|court)\b"),
    ("people", "Appointment / exit", r"\b(appoint\w*|nominat\w*|resign\w*|steps? down|ousted|fired|hires?|joins? (?:the )?board)\b"),
    ("political", "Endorsement / donation", r"\b(endors\w*|donat\w*|super pac|campaign|fundrais\w*)\b"),
]
_MOVE_RE = [(k, label, re.compile(p, re.I)) for k, label, p in MOVE_RULES]

# Issues a person is associated with. This describes what they talk about and get
# covered for, not where they sit politically.
TOPICS = {
    "Economy & inflation": r"\b(econom\w*|inflation|recession|interest rates?|jobs report|gdp|federal reserve|the fed)\b",
    "Taxes & spending": r"\b(tax\w*|spending|deficit|debt ceiling|budget)\b",
    "Trade & tariffs": r"\b(tariffs?|trade war|trade deal|exports?|imports?)\b",
    "Crypto": r"\b(crypto\w*|bitcoin|ethereum|stablecoin|dogecoin|blockchain|memecoin)\b",
    "AI & tech": r"\b(ai|artificial intelligence|chips?|semiconductor\w*|data cent(?:er|re)s?|robot\w*|software)\b",
    "Energy & oil": r"\b(oil|gas|energy|opec|nuclear|drilling|pipeline|solar|renewable\w*)\b",
    "Climate": r"\b(climate|emissions|net zero|carbon|green deal)\b",
    "Defence & war": r"\b(defen[cs]e|military|war|missile\w*|nato|troops|weapons?|drone\w*)\b",
    "Immigration": r"\b(immigra\w*|border|migrant\w*|asylum|deport\w*)\b",
    "Healthcare": r"\b(health\w*|medicare|medicaid|drug prices?|pharma\w*|vaccine\w*)\b",
    "Banking & markets": r"\b(bank\w*|stocks?|markets?|wall street|shares|investors?)\b",
    "China": r"\b(china|chinese|beijing|xi jinping)\b",
    "Russia & Ukraine": r"\b(russia\w*|ukrain\w*|putin|zelensky\w*|kremlin)\b",
    "Middle East": r"\b(israel\w*|gaza|iran\w*|saudi|hamas|hezbollah|middle east)\b",
    "Elections": r"\b(election\w*|vote\w*|ballot\w*|poll\w*|midterms?|primary)\b",
    "Media & entertainment": r"\b(film|movie|album|tour|streaming|box office|show|music)\b",
    "Sport": r"\b(football|soccer|nfl|nba|club|team|league|championship)\b",
}
_TOPIC_RE = {k: re.compile(p, re.I) for k, p in TOPICS.items()}


def item_text(item: Dict) -> str:
    return f"{item.get('title', '')} {item.get('summary', '')}"


def companies_in(text: str, known_tickers: Set[str] = frozenset()) -> List[Dict]:
    """[{"name": "NVIDIA", "ticker": "NVDA"}, {"name": "SpaceX", "ticker": ""}] mentioned in the text."""
    found: Dict[str, Dict] = {}
    for rx, name, ticker in _COMPANY_RE:
        if rx.search(text):
            found.setdefault(ticker, {"name": name, "ticker": ticker})
    for rx, name in _PRIVATE_RE:
        if rx.search(text):
            found.setdefault(name, {"name": name, "ticker": ""})
    for t in _CASHTAG.findall(text) + _EXCHANGE.findall(text):
        if t in found or (known_tickers and t not in known_tickers):
            continue
        found[t] = {"name": t, "ticker": t}
    return list(found.values())


def move_kinds(text: str) -> List[Dict]:
    """The power-move kinds a headline matches, each with the word that triggered it."""
    out = []
    for key, label, rx in _MOVE_RE:
        m = rx.search(text)
        if m:
            out.append({"kind": key, "label": label, "trigger": m.group(0).strip()})
    return out


def topics_in(text: str) -> List[str]:
    return [k for k, rx in _TOPIC_RE.items() if rx.search(text)]


def annotate(item: Dict, known_tickers: Set[str] = frozenset()) -> Dict:
    text = item_text(item)
    return {**item,
            "companies": companies_in(text, known_tickers),
            "moves": move_kinds(text),
            "topics": topics_in(text),
            "sentiment": round(sentiment.score(text), 3)}


def _tone_label(avg: float) -> str:
    if avg >= 0.15:
        return "positive"
    if avg <= -0.15:
        return "negative"
    return "mixed / neutral"


def traded(trades: Iterable[Dict]) -> List[Dict]:
    """Disclosed trades grouped by company: how many buys and sells, and the dollar total.
    House PTRs give ranges, so their totals use the bottom of each range."""
    out: Dict[str, Dict] = {}
    for t in trades:
        key = t.get("ticker") or t.get("company") or ""
        if not key:
            continue
        o = out.setdefault(key, {"name": t.get("company") or key, "ticker": t.get("ticker", ""),
                                 "buys": 0, "sells": 0, "value": 0.0, "last": ""})
        side = t.get("side") or {"new": "buy", "add": "buy", "trim": "sell", "exit": "sell"}.get(t.get("action"), "")
        if side == "buy":
            o["buys"] += 1
        elif side == "sell":
            o["sells"] += 1
        o["value"] += abs(t.get("value_change", t.get("value", 0.0)) or 0.0)
        o["last"] = max(o["last"], t.get("date", ""))
    return sorted(out.values(), key=lambda o: o["value"], reverse=True)[:15]


def summarize(items: Iterable[Dict], trades: Iterable[Dict] = ()) -> Dict:
    """Roll annotated items (and disclosed trades) up into a profile summary."""
    items = list(items)
    companies: Counter = Counter()
    meta: Dict[str, Dict] = {}
    for it in items:
        for c in it["companies"]:
            key = c["ticker"] or c["name"]
            companies[key] += 1
            meta.setdefault(key, c)
    topics = Counter(t for it in items for t in it["topics"])
    moves = Counter(m["label"] for it in items for m in it["moves"])
    own = [it for it in items if it.get("own_words")]
    coverage = [it for it in items if not it.get("own_words")]

    def tone(rows):
        if not rows:
            return None
        avg = sum(r["sentiment"] for r in rows) / len(rows)
        return {"avg": round(avg, 3), "label": _tone_label(avg), "items": len(rows)}

    total_topics = sum(topics.values()) or 1
    return {
        "companies": [{**meta[k], "mentions": n} for k, n in companies.most_common(15)],
        "traded": traded(trades),
        "topics": [{"topic": k, "mentions": n, "share": round(n / total_topics, 3)} for k, n in topics.most_common(8)],
        "move_kinds": [{"label": k, "count": n} for k, n in moves.most_common()],
        "tone": {"own_words": tone(own), "coverage": tone(coverage)},
    }
