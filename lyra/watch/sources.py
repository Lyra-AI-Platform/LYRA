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
# News stories about someone's posts: how X, Truth Social, Instagram and TikTok posts reach the
# tracker without reading those platforms (their terms forbid scraping and the APIs are paid).
POST_TERMS = ('(tweet OR tweeted OR "posted on X" OR "wrote on X" OR "said on X" OR "Truth Social" OR '
              '"Instagram post" OR "TikTok video" OR "Facebook post" OR "Threads post" OR "social media post")')
_PLATFORM_WORDS = [("Truth Social", r"truth social"), ("X", r"\btweet|\bon x\b|\bx post|twitter"),
                   ("Instagram", r"instagram"), ("TikTok", r"tiktok"), ("Facebook", r"facebook"),
                   ("Threads", r"\bthreads\b"), ("YouTube", r"youtube"), ("Bluesky", r"bluesky")]


_POST_HEADLINE = re.compile(
    r"\btweet(?:s|ed|ing)?\b|\b(?:posted|wrote|said|says|shared|posts|writes|claimed|claims) on (?:X|Twitter|Truth Social|"
    r"Instagram|TikTok|Facebook|Threads|Bluesky|social media)\b|\bTruth Social post|\b(?:X|Instagram|TikTok|Facebook|"
    r"Threads|social media) (?:post|video|rant|message)\b", re.I)


def reported_platform(text: str) -> str:
    """Which platform a news story says the post was on: "Musk tweeted..." -> "X"."""
    low = text.lower()
    return next((name for name, rx in _PLATFORM_WORDS if re.search(rx, low)), "Social media")
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

async def statements(person: Dict, max_age: float = 3 * 3600) -> Tuple[List[Dict], Dict]:
    """Headlines about the person (coverage) plus posts from their own RSS feeds (own words).
    max_age is how long a fetched feed is reused; the live loop asks for fresh copies."""
    query = person.get("news_query") or f'"{person["name"]}"'
    posts_url = NEWS_FEED.format(q=quote_plus(f"{query} {POST_TERMS}"), days=STATEMENT_DAYS)
    urls = [(NEWS_FEED.format(q=quote_plus(query), days=STATEMENT_DAYS), False), (posts_url, False)]
    own = [f if isinstance(f, dict) else {"url": f, "platform": platform_of(f)} for f in person.get("feeds", [])]
    urls += [(f["url"], True) for f in own]
    platforms = {f["url"]: f["platform"] for f in own}
    bodies = await asyncio.gather(*(fetch_text(u, max_age=max_age) for u, _ in urls))
    seen, items = set(), []
    for (url, own), body in zip(urls, bodies):
        for it in news.parse_feed(body or ""):
            key = it["title"].lower()[:80]
            if key in seen or _days_ago(datetime.fromtimestamp(it["published"], timezone.utc)
                                        .strftime("%Y-%m-%d")) > STATEMENT_DAYS:
                continue
            seen.add(key)
            extra = {"platform": platforms.get(url, "")} if own else {}
            # Only a headline that itself says it's about a post counts; Google's matching is loose.
            if not own and _POST_HEADLINE.search(it["title"]):
                extra = {"reported": True, "platform": reported_platform(it["title"])}
            items.append({**it, "summary": it["summary"][:news.SUMMARY_CHARS], "own_words": own, **extra})
    items.sort(key=lambda x: x["published"], reverse=True)
    failed = sum(b is None for b in bodies)
    status = {"status": "ok" if not failed else "failed" if failed == len(urls) else "partial",
              "provider": "Google News RSS" + (" + own feeds" if own else ""),
              "items": len(items)}
    return items[:120], status


# ── Wikipedia: who someone is and how many people read about them ──────────

WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_VIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
              "{title}/daily/{start}/{end}")
_PERSON_DESC = re.compile(
    r"\b(born|\(\d{4}|politician|business(?:man|woman|person)|executive|entrepreneur|investor|actor|actress|"
    r"singer|rapper|musician|songwriter|footballer|player|athlete|coach|journalist|author|writer|novelist|"
    r"president|minister|lawyer|judge|director|filmmaker|producer|presenter|host|economist|engineer|scientist|"
    r"activist|model|comedian|official|diplomat|monarch|king|queen|prince|princess|personality|billionaire|"
    r"philanthropist|banker|financier|commentator|influencer|youtuber|strategist|civil servant|cleric|"
    r"senator|congress(?:man|woman)|governor|mayor|member of)\b", re.I)


def _wiki_title(person: Dict) -> str:
    if person.get("wiki"):
        return person["wiki"]
    src = (person.get("affiliation") or {}).get("source", "")
    if "wikipedia.org/wiki/" in src:
        return src.rsplit("/wiki/", 1)[1]
    return re.sub(r"\s*\(.*?\)", "", person["name"]).strip().replace(" ", "_")


async def wiki_person(person: Dict) -> Dict:
    """{"status": "ok"|"none"|"unavailable", "title", "description", "url", "daily_views"} for a person.
    "none" means Wikipedia has no article about a person by that name."""
    title = _wiki_title(person)
    body = await fetch_text(WIKI_SUMMARY.format(title=quote_plus(title, safe="_%")), max_age=7 * 86400,
                            headers={"User-Agent": SEC_USER_AGENT})
    if body is None:
        # fetch_text gives None for a 404 and for an outage alike; a page that always exists tells them apart.
        probe = await fetch_text("https://en.wikipedia.org/api/rest_v1/page/summary/Wikipedia", max_age=3600,
                                 headers={"User-Agent": SEC_USER_AGENT})
        return {"status": "none" if probe else "unavailable"}
    try:
        page = json.loads(body)
    except ValueError:
        return {"status": "unavailable"}
    desc = page.get("description") or ""
    if page.get("type") != "standard" or not _PERSON_DESC.search(desc + " " + (page.get("extract") or "")[:200]):
        return {"status": "none"}
    canonical = (page.get("titles") or {}).get("canonical") or page.get("title", title).replace(" ", "_")
    end = datetime.now(timezone.utc)
    start = end.fromtimestamp(end.timestamp() - 30 * 86400, timezone.utc)
    views_body = await fetch_text(WIKI_VIEWS.format(title=quote_plus(canonical, safe="_%"),
                                                    start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d")),
                                  max_age=86400, headers={"User-Agent": SEC_USER_AGENT})
    daily = None
    try:
        rows = json.loads(views_body)["items"] if views_body else []
        daily = sum(r["views"] for r in rows) / max(len(rows), 1) if rows else None
    except (ValueError, KeyError):
        pass
    return {"status": "ok", "title": canonical, "description": desc, "qid": page.get("wikibase_item", ""),
            "url": (page.get("content_urls") or {}).get("desktop", {}).get("page", ""), "daily_views": daily}


WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
WIKIDATA_LABELS = "https://www.wikidata.org/w/api.php?action=wbgetentities&ids={ids}&props=labels&languages=en&format=json"


def _claims(entity: Dict, prop: str, current_only: bool) -> List[str]:
    """Item ids for a property, skipping deprecated statements and (optionally) ones with an end date."""
    out = []
    for st in entity.get("claims", {}).get(prop, []):
        if st.get("rank") == "deprecated" or (current_only and "P582" in st.get("qualifiers", {})):
            continue
        value = st.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
    return list(dict.fromkeys(out))


async def wikidata_profile(qid: str) -> Dict:
    """Documented public facts from Wikidata: current party membership (P102), offices held
    now (P39) and occupations (P106). Nothing here is inferred; every item is a sourced statement."""
    if not re.fullmatch(r"Q\d+", qid or ""):
        return {}
    body = await fetch_text(WIKIDATA_ENTITY.format(qid=qid), max_age=7 * 86400, headers={"User-Agent": SEC_USER_AGENT})
    try:
        entity = next(iter(json.loads(body)["entities"].values())) if body else {}
    except (ValueError, KeyError, StopIteration):
        return {}
    ids = {"parties": _claims(entity, "P102", True)[:3], "offices": _claims(entity, "P39", True)[:4],
           "occupations": _claims(entity, "P106", False)[:4]}
    accounts = {name: _strings(entity, prop) for name, prop in ACCOUNT_PROPS.items()}
    wanted = sorted({i for v in ids.values() for i in v})
    labels: Dict[str, str] = {}
    if wanted:
        lb = await fetch_text(WIKIDATA_LABELS.format(ids="|".join(wanted)), max_age=30 * 86400,
                              headers={"User-Agent": SEC_USER_AGENT})
        try:
            labels = {k: v["labels"]["en"]["value"] for k, v in json.loads(lb)["entities"].items()
                      if v.get("labels", {}).get("en")} if lb else {}
        except (ValueError, KeyError):
            labels = {}
    return {k: [labels[i] for i in v if i in labels] for k, v in ids.items()} | {
        "accounts": {k: v for k, v in accounts.items() if v}, "source": f"https://www.wikidata.org/wiki/{qid}"}


# ── Their own accounts ─────────────────────────────────────────────────────
# Official accounts listed on Wikidata. Platforms with a free public feed are read; the rest
# (X, Instagram, Facebook, Threads, TikTok have no free feed and forbid scraping) are linked only.

ACCOUNT_PROPS = {"youtube": "P2397", "bluesky": "P12361", "mastodon": "P4033", "website": "P856",
                 "x": "P2002", "instagram": "P2003", "facebook": "P2013", "threads": "P11892", "tiktok": "P7085"}
ACCOUNT_LINKS = {"youtube": "https://www.youtube.com/channel/{}", "bluesky": "https://bsky.app/profile/{}",
                 "x": "https://x.com/{}", "instagram": "https://www.instagram.com/{}/",
                 "facebook": "https://www.facebook.com/{}", "threads": "https://www.threads.net/@{}",
                 "tiktok": "https://www.tiktok.com/@{}", "website": "{}"}
READABLE = ("youtube", "bluesky", "mastodon", "website")


def _strings(entity: Dict, prop: str) -> List[str]:
    out = []
    for st in entity.get("claims", {}).get(prop, []):
        value = st.get("mainsnak", {}).get("datavalue", {}).get("value")
        if st.get("rank") != "deprecated" and isinstance(value, str) and value.strip():
            out.append(value.strip())
    return list(dict.fromkeys(out))[:3]


def _mastodon(address: str) -> Tuple[str, str]:
    """"user@mastodon.social" -> ("https://mastodon.social/@user", feed url)."""
    user, _, host = address.lstrip("@").partition("@")
    if not (user and re.fullmatch(r"[\w.-]+\.[a-z]{2,}", host or "")):
        return "", ""
    return f"https://{host}/@{user}", f"https://{host}/@{user}.rss"


def account_links(accounts: Dict[str, List[str]]) -> List[Dict]:
    """[{"platform": "x", "handle": "elonmusk", "url": "https://x.com/elonmusk", "read": False}, ...]"""
    out = []
    for platform, handles in accounts.items():
        for h in handles:
            url = _mastodon(h)[0] if platform == "mastodon" else ACCOUNT_LINKS.get(platform, "").format(h)
            if url.startswith("http"):
                out.append({"platform": platform, "handle": h, "url": url, "read": platform in READABLE})
    return out


def platform_of(url: str) -> str:
    host = re.sub(r"^www\.", "", url.split("//", 1)[-1].split("/", 1)[0])
    return {"youtube.com": "YouTube", "bsky.app": "Bluesky"}.get(host, "Mastodon" if "/@" in url else "Website")


_FEED_LINK = re.compile(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)


async def _site_feed(site: str, person: Dict) -> Optional[str]:
    """The RSS/Atom feed an official website advertises, if the site is the person's own
    (their name in the address, or a government site) rather than a company's."""
    host = site.split("//", 1)[-1].split("/", 1)[0].lower()
    names = [n.lower() for n in re.sub(r"\s*\(.*?\)", "", person["name"]).split() if len(n) > 2]
    if not (any(n in host for n in names) or host.endswith((".gov", ".gov.uk", ".gouv.fr", ".gov.br"))):
        return None
    html = await fetch_text(site, max_age=7 * 86400)
    for tag in _FEED_LINK.findall(html or ""):
        href = re.search(r"href=[\"']([^\"']+)", tag)
        if href and "comment" not in tag.lower():
            url = href.group(1)
            return url if url.startswith("http") else site.rstrip("/") + "/" + url.lstrip("/")
    return None


async def own_feeds(person: Dict, accounts: Dict[str, List[str]]) -> List[Dict]:
    """Free public feeds of the person's own accounts, kept only if they load and have posts:
    [{"platform": "YouTube", "url": ..., "posts": 15}]. Feeds listed in the roster come first."""
    candidates = [(platform_of(u), u) for u in person.get("feeds", [])]
    candidates += [("YouTube", f"https://www.youtube.com/feeds/videos.xml?channel_id={c}")
                   for c in accounts.get("youtube", []) if re.fullmatch(r"UC[\w-]{22}", c)]
    candidates += [("Bluesky", f"https://bsky.app/profile/{h}/rss") for h in accounts.get("bluesky", [])]
    candidates += [("Mastodon", _mastodon(a)[1]) for a in accounts.get("mastodon", []) if _mastodon(a)[1]]
    for site in accounts.get("website", [])[:2]:
        feed = await _site_feed(site, person)
        if feed:
            candidates.append(("Website", feed))
    out = []
    for platform, url in dict((u, (p, u)) for p, u in candidates).values():
        body = await fetch_text(url, max_age=6 * 3600)
        posts = len(news.parse_feed(body or ""))
        if posts:
            out.append({"platform": platform, "url": url, "posts": posts})
    return out
