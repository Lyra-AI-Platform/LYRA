"""News gathering: pulls every headline for a ticker from RSS feeds, keeps only
articles that actually mention the company, scores their sentiment and stores
headline + short summary + link. Full article text is never fetched or shown:
republishing third-party articles is a copyright problem."""
import asyncio
import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, List
from urllib.parse import quote_plus, urlparse

from lyra.market import sentiment
from lyra.market.config import MARKET_FEEDS, TICKER_FEEDS
from lyra.market.fetch import fetch_text
from lyra.market.store import get_store

logger = logging.getLogger(__name__)
SUMMARY_CHARS = 300

_NAME_SUFFIXES = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|LLC|HOLDINGS|HLDGS|GROUP|SA|NV|AG|THE)\b\.?",
    re.I)
_GENERIC_FIRST_WORDS = {"UNITED", "AMERICAN", "GENERAL", "FIRST", "NATIONAL", "INTERNATIONAL", "GLOBAL",
                        "SOUTHERN", "NORTHERN", "WESTERN", "EASTERN", "PACIFIC", "ATLANTIC", "ADVANCED"}


def _strip_html(s: str) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(s or "", "html.parser").get_text(" ", strip=True)


def _parse_date(s: str) -> float:
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        return time.time()


def _first(fields: Dict, *names):
    # Elements without children are falsy, so `a or b` can't be used here.
    for n in names:
        if fields.get(n) is not None:
            return fields[n]
    return None


def parse_feed(body: str) -> List[Dict]:
    """Parse RSS 2.0 or Atom into [{"title","url","summary","published","source"}]."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter():
        tag = item.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        fields = {c.tag.split("}")[-1]: c for c in item}
        link = fields.get("link")
        url = ""
        if link is not None:
            url = (link.text or link.get("href") or "").strip()
        title = _strip_html(fields["title"].text if "title" in fields else "")
        summary_el = _first(fields, "description", "summary", "content")
        source_el = fields.get("source")
        date_el = _first(fields, "pubDate", "published", "updated")
        if not title or not url:
            continue
        items.append({
            "title": title,
            "url": url,
            "summary": _strip_html(summary_el.text if summary_el is not None else "")[:1000],
            "published": _parse_date(date_el.text) if date_el is not None and date_el.text else time.time(),
            "source": (source_el.text if source_el is not None and source_el.text else urlparse(url).netloc),
        })
    return items


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def company_core(company: str) -> str:
    """"NVIDIA CORP" -> "NVIDIA", "Apple Inc." -> "Apple"."""
    return " ".join(_NAME_SUFFIXES.sub(" ", re.sub(r"[,.]", " ", company or "")).split())


def mentions(item: Dict, ticker: str, company: str = "") -> bool:
    """True if the title or summary names the ticker or the company."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    if re.search(rf"(?<![A-Za-z]){re.escape(ticker.upper())}(?![A-Za-z])", text):
        return True
    core = company_core(company)
    names = {core} if core else set()
    first = core.split()[0] if core else ""
    # "AMAZON COM" is written "Amazon" in headlines; skip first words that name many companies.
    if len(first) >= 5 and first.upper() not in _GENERIC_FIRST_WORDS:
        names.add(first)
    return any(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n in names)


async def collect_news_report(ticker: str, company: str = "") -> Dict:
    """Gather, filter, score and store the latest articles for a ticker ("MARKET" for general
    market news). Returns the articles plus a per-feed status and how many were off-topic."""
    ticker = ticker.upper()
    if ticker == "MARKET":
        urls = MARKET_FEEDS
    else:
        q = quote_plus(f'"{company}"' if company else ticker)
        urls = [u.format(t=ticker, q=q) for u in TICKER_FEEDS]
    bodies = await asyncio.gather(*(fetch_text(u, max_age=900) for u in urls))
    feeds = [{"feed": urlparse(u).netloc, "status": "ok" if b else "failed"} for u, b in zip(urls, bodies)]
    for f in feeds:
        if f["status"] == "failed":
            logger.warning(f"News feed {f['feed']} failed for {ticker}")
    seen, items, off_topic = set(), [], 0
    for body in bodies:
        for it in parse_feed(body or ""):
            key = it["title"].lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            if ticker != "MARKET" and not mentions(it, ticker, company):
                off_topic += 1
                continue
            items.append(it)
    items.sort(key=lambda x: x["published"], reverse=True)

    store = get_store()
    for it in items:
        it.update({
            "id": article_id(it["url"]),
            "ticker": ticker,
            "summary": it["summary"][:SUMMARY_CHARS],
            "sentiment": round(sentiment.score(f"{it['title']} {it['title']} {it['summary']}"), 3),
        })
        store.save_article(it)
    ok = sum(f["status"] == "ok" for f in feeds)
    status = "ok" if ok == len(feeds) else "failed" if ok == 0 else "partial"
    return {"articles": items, "status": status, "feeds": feeds, "off_topic_dropped": off_topic}


async def collect_news(ticker: str, company: str = "") -> List[Dict]:
    return (await collect_news_report(ticker, company))["articles"]


def news_features(articles: List[Dict], now: float = None) -> Dict:
    """Recency-weighted sentiment and how much the stock is being talked about."""
    now = now or time.time()
    week = [a for a in articles if now - a["published"] <= 7 * 86400]
    if not week:
        return {"count_7d": 0, "sentiment": 0.0}
    weights = [0.5 ** ((now - a["published"]) / (2 * 86400)) for a in week]  # 2-day half-life
    sent = sum(w * a["sentiment"] for w, a in zip(weights, week)) / sum(weights)
    return {"count_7d": len(week), "sentiment": round(sent, 4)}
