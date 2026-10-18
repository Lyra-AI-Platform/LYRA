"""News gathering: pulls every headline for a ticker from RSS feeds, fetches
the full article text where the site allows it, scores sentiment, and keeps it
all in the local database so it can be read in one place in the Lyra UI."""
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
MAX_FULL_TEXT = 20000


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


def extract_article_text(html: str) -> str:
    """Reader-mode extraction: prefer <article>, else the block with the most paragraph text."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    container = soup.find("article")
    if container is None:
        best, best_len = None, 0
        for parent in {p.parent for p in soup.find_all("p") if p.parent is not None}:
            length = sum(len(p.get_text(strip=True)) for p in parent.find_all("p", recursive=False))
            if length > best_len:
                best, best_len = parent, length
        container = best
    if container is None:
        return ""
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if len(p) > 40)
    return re.sub(r"[ \t]+", " ", text)[:MAX_FULL_TEXT]


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


async def _full_text(url: str) -> str:
    html = await fetch_text(url, max_age=7 * 86400, timeout=12)
    return extract_article_text(html) if html else ""


async def collect_news(ticker: str, company: str = "", fetch_full: bool = True, max_full: int = 12) -> List[Dict]:
    """Gather, store and return the latest articles for a ticker ("MARKET" for general market news)."""
    ticker = ticker.upper()
    if ticker == "MARKET":
        urls = MARKET_FEEDS
    else:
        q = quote_plus(f'"{company}"' if company else ticker)
        urls = [u.format(t=ticker, q=q) for u in TICKER_FEEDS]
    bodies = await asyncio.gather(*(fetch_text(u, max_age=900) for u in urls))
    seen, items = set(), []
    for body in bodies:
        for it in parse_feed(body or ""):
            key = it["title"].lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
    items.sort(key=lambda x: x["published"], reverse=True)

    texts = [""] * len(items)
    if fetch_full:
        texts[:max_full] = await asyncio.gather(*(_full_text(it["url"]) for it in items[:max_full]))

    store = get_store()
    for it, text in zip(items, texts):
        it.update({
            "id": article_id(it["url"]),
            "ticker": ticker,
            "full_text": text,
            "sentiment": round(sentiment.score(f"{it['title']} {it['title']} {it['summary']} {text[:3000]}"), 3),
        })
        store.save_article(it)
    return items


def news_features(articles: List[Dict], now: float = None) -> Dict:
    """Recency-weighted sentiment and how much the stock is being talked about."""
    now = now or time.time()
    week = [a for a in articles if now - a["published"] <= 7 * 86400]
    if not week:
        return {"count_7d": 0, "sentiment": 0.0}
    weights = [0.5 ** ((now - a["published"]) / (2 * 86400)) for a in week]  # 2-day half-life
    sent = sum(w * a["sentiment"] for w, a in zip(weights, week)) / sum(weights)
    return {"count_7d": len(week), "sentiment": round(sent, 4)}
