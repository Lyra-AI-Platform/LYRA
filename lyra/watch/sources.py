"""Public-record sources for the watchlist:

- SEC EDGAR Form 4: trades filed by a person as a company insider (by their own CIK).
- SEC EDGAR 13F: quarter-on-quarter position changes of a person's fund.
- US House Clerk: Periodic Transaction Reports (STOCK Act), parsed from the PDFs.
- Google News RSS (+ any RSS feeds of the person's own accounts) for statements and coverage.

X/Twitter and Facebook aren't read: their terms forbid scraping and their APIs are paid.
Own-account feeds that publish RSS (Bluesky, YouTube, Substack, blogs) can be added per
person in the roster's "feeds" list."""
import asyncio
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus

import httpx

from lyra.market import news
from lyra.market.config import SEC_USER_AGENT
from lyra.market.fetch import fetch_text
from lyra.market.smart_money import (SEC_ARCHIVE, SEC_FILING, SEC_SUBMISSIONS, SEC_TICKERS, _days_ago,
                                     _fund_filings, _fund_holdings, parse_form4)
from lyra.watch.config import LOOKBACK_DAYS, STATEMENT_DAYS, WATCH_DIR

logger = logging.getLogger(__name__)

HOUSE_INDEX = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
HOUSE_PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc}.pdf"
NEWS_FEED = "https://news.google.com/rss/search?q={q}+when:{days}d&hl=en-US&gl=US&ceid=US:en"
_SEC_NAME_NOISE = re.compile(r"\s*/[A-Z]{2,}/?\s*$|\s+(?:INC|CORP|CO|LTD|PLC|HOLDINGS?)\.?$", re.I)


def clean_company(name: str) -> str:
    """"LENNAR CORP /NEW/" -> "Lennar"; names already in mixed case are kept."""
    n = (name or "").strip()
    for _ in range(2):
        n = _SEC_NAME_NOISE.sub("", n).strip(" ,.")
    return n.title() if n.isupper() and len(n) > 4 else n


def _ok(provider: str, **extra) -> Dict:
    return {"status": "ok", "provider": provider, **extra}


def _failed(provider: str, detail: str) -> Dict:
    return {"status": "failed", "provider": provider, "detail": detail}


async def known_tickers() -> Set[str]:
    body = await fetch_text(SEC_TICKERS, max_age=7 * 86400)
    try:
        return {r["ticker"].upper() for r in json.loads(body).values()} if body else set()
    except (ValueError, KeyError):
        return set()


# ── SEC Form 4 filed by the person ─────────────────────────────────────────

async def form4_trades(cik: str, max_filings: int = 25) -> Tuple[List[Dict], Dict]:
    provider = "SEC EDGAR (Form 4)"
    body = await fetch_text(SEC_SUBMISSIONS.format(cik=cik), max_age=6 * 3600)
    if not body:
        return [], _failed(provider, "filing list unavailable")
    recent = json.loads(body).get("filings", {}).get("recent", {})
    docs = []
    for form, acc, date, doc in zip(recent.get("form", []), recent.get("accessionNumber", []),
                                    recent.get("filingDate", []), recent.get("primaryDocument", [])):
        if form == "4" and _days_ago(date) <= LOOKBACK_DAYS:
            docs.append(SEC_ARCHIVE.format(cik=int(cik), acc=acc.replace("-", ""), doc=doc.split("/")[-1]))
        if len(docs) >= max_filings:
            break
    bodies = await asyncio.gather(*(fetch_text(u, max_age=30 * 86400) for u in docs))
    trades = []
    for url, xml_text in zip(docs, bodies):
        for t in parse_form4(xml_text or ""):
            trades.append({**t, "company": clean_company(t.get("company", "")),
                           "ticker": t.get("ticker", "").split(",")[0].strip(), "url": url, "kind": "insider"})
    missing = sum(b is None for b in bodies)
    status = _ok(provider, filings=len(docs))
    if missing:
        status.update(status="partial", detail=f"{missing} of {len(docs)} filings could not be read")
    return trades, status


# ── 13F: what the person's fund added and cut ──────────────────────────────

def position_changes(latest: List[Dict], prior: List[Dict], top: int = 8) -> List[Dict]:
    """Biggest new, added, trimmed and exited positions between two 13F filings, by value."""
    def by_cusip(rows):
        out: Dict[str, Dict] = {}
        for r in rows:
            if r.get("put_call"):
                continue
            o = out.setdefault(r["cusip"], {"issuer": r["issuer"], "shares": 0.0, "value": 0.0})
            o["shares"] += r["shares"]
            o["value"] += r["value"]
        return out
    now, before = by_cusip(latest), by_cusip(prior)
    changes = []
    for cusip in set(now) | set(before):
        a, b = now.get(cusip), before.get(cusip)
        shares_now, shares_before = (a or {}).get("shares", 0.0), (b or {}).get("shares", 0.0)
        if shares_now == shares_before:
            continue
        action = ("new" if not b else "exit" if not a else "add" if shares_now > shares_before else "trim")
        price = ((a or b)["value"] / (a or b)["shares"]) if (a or b)["shares"] else 0.0
        changes.append({"company": clean_company((a or b)["issuer"]), "action": action,
                        "shares_change": shares_now - shares_before,
                        "value_change": round((shares_now - shares_before) * price, 2),
                        "value_now": round((a or {}).get("value", 0.0), 2)})
    changes.sort(key=lambda c: abs(c["value_change"]), reverse=True)
    return changes[:top]


async def fund_moves(cik: str) -> Tuple[List[Dict], Dict]:
    provider = "SEC EDGAR (13F)"
    try:
        filings = await _fund_filings(cik)
    except RuntimeError as e:
        return [], _failed(provider, str(e))
    if not filings:
        return [], _failed(provider, "no 13F filings found")
    latest = await _fund_holdings(cik, filings[0]["acc"])
    prior = await _fund_holdings(cik, filings[1]["acc"]) if len(filings) > 1 else []
    moves = [{**m, "date": filings[0]["date"], "url": SEC_FILING.format(cik=int(cik), acc=filings[0]["acc"]),
              "kind": "fund"} for m in position_changes(latest, prior)]
    return moves, _ok(provider, as_of=filings[0]["date"],
                      detail="13F holdings are filed up to 45 days after each quarter ends")


# ── US House Periodic Transaction Reports ──────────────────────────────────

def parse_house_index(xml_text: str) -> List[Dict]:
    """Every PTR (FilingType P) in the Clerk's yearly index."""
    out = []
    for m in re.finditer(r"<Member>(.*?)</Member>", xml_text, re.S):
        block = m.group(1)

        def tag(name):
            t = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
            return (t.group(1).strip() if t else "")
        if tag("FilingType") != "P":
            continue
        out.append({"last": tag("Last"), "first": tag("First"), "state": tag("StateDst"),
                    "date": tag("FilingDate"), "doc": tag("DocID"), "year": tag("Year")})
    return out


_PTR_ROW = re.compile(
    r"(?:\((?P<ticker>[A-Z][A-Z.\-]{0,6})\)\s*)?(?:\[(?P<atype>[A-Z]{2})\]\s*)?"
    r"(?P<type>P|S \(partial\)|S|E)\s+(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<notified>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>\$[\d,]+\s*-\s*\$[\d,]+|Over \$[\d,]+|\$[\d,]+)")
_OWNER_PREFIX = re.compile(r"^(?:SP|JT|DC)\s+")
_DESCRIPTION = re.compile(r"\nD\s*:\s*(.+?)(?=\n\*|\n(?:SP|JT|DC)\s|\Z)", re.S)


def parse_ptr_text(text: str) -> List[Dict]:
    """Transactions from the text of an electronically filed House PTR: stocks, options,
    funds and private holdings (LLCs, real estate), with the filer's description."""
    text = text.replace("\x00", "")
    # Each new page repeats the filing ID and the table header.
    text = re.sub(r"Filing ID #\d+\s*ID Owner Asset.*?\$200\?", "\n", text, flags=re.S)
    header = text.find("$200?")
    pos = header + 5 if header >= 0 else 0
    rows = [m for m in _PTR_ROW.finditer(text, pos) if m.group("ticker") or m.group("atype")]
    trades = []
    for i, m in enumerate(rows):
        asset = " ".join(text[pos:m.start()].split())
        asset = _OWNER_PREFIX.sub("", asset).replace(" - Common Stock", "").strip(" -")
        tail = text[m.end():rows[i + 1].start() if i + 1 < len(rows) else len(text)]
        d = _DESCRIPTION.search(tail)
        pos = m.end() + (d.end() if d else 0)  # the next row's asset name follows the description
        kind = m.group("type")
        side = "buy" if kind == "P" else "sell" if kind.startswith("S") else "exchange"
        amount = " ".join(m.group("amount").split())
        nums = re.findall(r"[\d,]+", amount)
        try:
            date = datetime.strptime(m.group("date"), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        # The amount's second line and the "F S: New" status line can trail the asset text.
        asset = re.sub(r"^(?:\$[\d,]+\s*)?(?:F\s*S\s*:\s*\w+\s*)?", "", asset)
        asset = re.sub(r"\s*\*.*$", "", asset)
        trades.append({"company": asset[-90:], "ticker": m.group("ticker") or "", "side": side,
                       "partial": "partial" in kind, "asset_type": m.group("atype") or "",
                       "options": m.group("atype") == "OP", "amount_range": amount,
                       "value": float(nums[0].replace(",", "")) if nums else 0.0, "date": date,
                       "description": " ".join(d.group(1).split())[:300] if d else ""})
    return trades


async def _fetch_bytes(url: str, timeout: float = 30) -> Optional[bytes]:
    cache = WATCH_DIR / "pdf" / (re.sub(r"[^A-Za-z0-9]+", "_", url.split("//", 1)[-1])[-120:])
    if cache.exists():
        return cache.read_bytes()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": SEC_USER_AGENT}) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(resp.content)
        return resp.content
    except Exception as e:  # noqa: BLE001
        logger.debug(f"GET {url} failed: {e}")
        return None


_index_cache: Dict[int, Tuple[float, List[Dict]]] = {}


async def house_index(year: int) -> Optional[List[Dict]]:
    now = datetime.now(timezone.utc).timestamp()
    hit = _index_cache.get(year)
    if hit and now - hit[0] < 12 * 3600:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                     headers={"User-Agent": SEC_USER_AGENT}) as client:
            resp = await client.get(HOUSE_INDEX.format(year=year))
        if resp.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
            rows = parse_house_index(z.read(name).decode("utf-8-sig", "replace"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"House disclosure index {year} unavailable: {e}")
        return None
    _index_cache[year] = (now, rows)
    return rows


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    try:
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001
        return ""


async def house_trades(last: str, state: str) -> Tuple[List[Dict], Dict]:
    provider = "US House Clerk (STOCK Act PTRs)"
    year = datetime.now(timezone.utc).year
    filings = []
    for y in (year, year - 1):
        rows = await house_index(y)
        if rows is None:
            if y == year:
                return [], _failed(provider, "disclosure index unavailable")
            continue
        filings += [r for r in rows if r["last"].lower() == last.lower() and r["state"] == state]
    filings = [f for f in filings if _days_ago(_us_date(f["date"])) <= LOOKBACK_DAYS]
    trades, unreadable = [], 0
    for f in filings:
        url = HOUSE_PTR.format(year=f["year"], doc=f["doc"])
        data = await _fetch_bytes(url)
        rows = parse_ptr_text(_pdf_text(data)) if data else []
        if not rows:
            unreadable += 1  # scanned paper filings have no text layer
            trades.append({"company": "Periodic Transaction Report (see PDF)", "ticker": "", "side": "filed",
                           "amount_range": "", "value": 0.0, "date": _us_date(f["date"]), "url": url,
                           "kind": "congress", "source": "House PTR"})
            continue
        for t in rows:
            trades.append({**t, "filed": _us_date(f["date"]), "url": url, "kind": "congress",
                           "source": "House PTR"})
    status = _ok(provider, filings=len(filings))
    if unreadable:
        status.update(detail=f"{unreadable} filing(s) are scanned or unparsed; open the PDF")
    return trades, status


def _us_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


# ── Statements and coverage ────────────────────────────────────────────────

async def statements(person: Dict) -> Tuple[List[Dict], Dict]:
    """Headlines about the person (coverage) plus posts from their own RSS feeds (own words)."""
    query = quote_plus(person.get("news_query") or f'"{person["name"]}"')
    urls = [(NEWS_FEED.format(q=query, days=STATEMENT_DAYS), False)]
    urls += [(u, True) for u in person.get("feeds", [])]
    bodies = await asyncio.gather(*(fetch_text(u, max_age=3 * 3600) for u, _ in urls))
    seen, items = set(), []
    for (url, own), body in zip(urls, bodies):
        for it in news.parse_feed(body or ""):
            key = it["title"].lower()[:80]
            if key in seen or _days_ago(datetime.fromtimestamp(it["published"], timezone.utc)
                                        .strftime("%Y-%m-%d")) > STATEMENT_DAYS:
                continue
            seen.add(key)
            items.append({**it, "summary": it["summary"][:news.SUMMARY_CHARS], "own_words": own})
    items.sort(key=lambda x: x["published"], reverse=True)
    failed = sum(b is None for b in bodies)
    status = {"status": "ok" if not failed else "failed" if failed == len(urls) else "partial",
              "provider": "Google News RSS" + (" + own feeds" if len(urls) > 1 else ""),
              "items": len(items)}
    return items[:80], status
