"""Smart-money tracking: what company insiders (CEOs, CFOs, directors),
famous funds and politicians are buying and selling.

Pure price maths can't see trades made on better information, so these
flows are weighted by who made them: a CEO buying their own stock on the
open market says much more than a director's scheduled sale."""
import asyncio
import json
import logging
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from lyra.market.config import (CONGRESS_SOURCES, LOOKBACK_DAYS_CONGRESS, LOOKBACK_DAYS_INSIDERS,
                                NOTABLE_FUNDS, ROLE_WEIGHTS, SELL_DISCOUNT, load_notable_trades)
from lyra.market.fetch import fetch_text

logger = logging.getLogger(__name__)

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SEC_INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
SEC_FILING = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"


def _days_ago(date_str: str) -> float:
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (time.time() - d.timestamp()) / 86400
    except (ValueError, TypeError):
        return 1e9


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(el: Optional[ET.Element], path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text else default


def role_weight(title: str) -> float:
    t = (title or "").lower()
    return max((w for k, w in ROLE_WEIGHTS.items() if k in t), default=0.5)


async def lookup_company(ticker: str) -> Optional[Dict]:
    """{"cik": "0000320193", "name": "Apple Inc."} or None."""
    body = await fetch_text(SEC_TICKERS, max_age=7 * 86400)
    if not body:
        return None
    for row in json.loads(body).values():
        if row["ticker"].upper() == ticker.upper():
            return {"cik": str(row["cik_str"]).zfill(10), "name": row["title"]}
    return None


# ── Insiders (SEC Form 4) ───────────────────────────────────────────────────

def parse_form4(xml_text: str) -> List[Dict]:
    """Open-market buys (P) and sells (S) from a Form 4 XML document."""
    try:
        root = _strip_ns(ET.fromstring(xml_text))
    except ET.ParseError:
        return []
    owner = root.find("reportingOwner")
    rel = owner.find("reportingOwnerRelationship") if owner is not None else None
    name = _text(owner, "reportingOwnerId/rptOwnerName")
    parts = []
    if _text(rel, "officerTitle"):
        parts.append(_text(rel, "officerTitle"))
    if _text(rel, "isOfficer") in ("1", "true") and not parts:
        parts.append("Officer")
    if _text(rel, "isDirector") in ("1", "true"):
        parts.append("Director")
    if _text(rel, "isTenPercentOwner") in ("1", "true"):
        parts.append("10% Owner")
    role = ", ".join(parts) or "Insider"
    trades = []
    for tx in root.iter("nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue  # grants, option exercises and gifts aren't conviction signals
        try:
            shares = float(_text(tx, "transactionAmounts/transactionShares/value", "0"))
            price = float(_text(tx, "transactionAmounts/transactionPricePerShare/value", "0") or 0)
        except ValueError:
            continue
        trades.append({
            "person": name, "role": role, "side": "buy" if code == "P" else "sell",
            "shares": shares, "price": price, "value": round(shares * price, 2),
            "date": _text(tx, "transactionDate/value"), "source": "SEC Form 4",
        })
    return trades


async def insider_trades(cik: str, max_filings: int = 30) -> Tuple[List[Dict], Dict]:
    body = await fetch_text(SEC_SUBMISSIONS.format(cik=cik), max_age=6 * 3600)
    if not body:
        logger.warning(f"SEC submissions unavailable for CIK {cik}")
        return [], {"status": "failed", "provider": "SEC EDGAR (Form 4)", "detail": "filing list unavailable"}
    recent = json.loads(body).get("filings", {}).get("recent", {})
    docs = []
    for form, acc, date, doc in zip(recent.get("form", []), recent.get("accessionNumber", []),
                                    recent.get("filingDate", []), recent.get("primaryDocument", [])):
        if form == "4" and _days_ago(date) <= LOOKBACK_DAYS_INSIDERS:
            raw_doc = doc.split("/")[-1]  # drop the xsl rendering folder to get raw XML
            docs.append(SEC_ARCHIVE.format(cik=int(cik), acc=acc.replace("-", ""), doc=raw_doc))
        if len(docs) >= max_filings:
            break
    bodies = await asyncio.gather(*(fetch_text(u, max_age=30 * 86400) for u in docs))
    trades = []
    for url, xml_text in zip(docs, bodies):
        for t in parse_form4(xml_text or ""):
            t["url"] = url
            trades.append(t)
    missing = sum(b is None for b in bodies)
    status = {"status": "ok" if not missing else "partial", "provider": "SEC EDGAR (Form 4)",
              "filings": len(docs)}
    if missing:
        status["detail"] = f"{missing} of {len(docs)} filings could not be read"
    return trades, status


# ── Notable funds (13F) ─────────────────────────────────────────────────────

_SUFFIXES = re.compile(r"\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|PLC|LLC|HLDGS|HOLDINGS|GROUP|CL|CLASS|"
                       r"COM|NEW|THE|SA|NV|AG|ADR|SPONSORED|SHS|A|B|C)\b")


def normalize_issuer(name: str) -> str:
    n = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
    return " ".join(_SUFFIXES.sub(" ", n).split())


def parse_13f_infotable(xml_text: str) -> List[Dict]:
    try:
        root = _strip_ns(ET.fromstring(xml_text))
    except ET.ParseError:
        return []
    rows = []
    for info in root.iter("infoTable"):
        try:
            rows.append({
                "issuer": _text(info, "nameOfIssuer"),
                "cusip": _text(info, "cusip"),
                "value": float(_text(info, "value", "0")),
                "shares": float(_text(info, "shrsOrPrnAmt/sshPrnamt", "0")),
                "put_call": _text(info, "putCall"),
            })
        except ValueError:
            continue
    return rows


async def _fund_filings(cik: str, count: int = 2) -> List[Dict]:
    body = await fetch_text(SEC_SUBMISSIONS.format(cik=cik), max_age=86400)
    if not body:
        raise RuntimeError("filing list unavailable")
    recent = json.loads(body).get("filings", {}).get("recent", {})
    out = []
    for form, acc, date in zip(recent.get("form", []), recent.get("accessionNumber", []), recent.get("filingDate", [])):
        if form == "13F-HR":
            out.append({"acc": acc.replace("-", ""), "date": date})
        if len(out) >= count:
            break
    return out


async def _fund_holdings(cik: str, acc: str) -> List[Dict]:
    index = await fetch_text(SEC_INDEX.format(cik=int(cik), acc=acc), max_age=90 * 86400)
    if not index:
        return []
    names = [i["name"] for i in json.loads(index).get("directory", {}).get("item", [])]
    table = next((n for n in names if n.lower().endswith(".xml") and "primary_doc" not in n.lower()), None)
    if not table:
        return []
    body = await fetch_text(SEC_ARCHIVE.format(cik=int(cik), acc=acc, doc=table), max_age=90 * 86400)
    return parse_13f_infotable(body or "")


def _match_position(holdings: List[Dict], company: str) -> Dict:
    # 13F issuer names are abbreviated differently from SEC company names, so
    # compare the first two significant words ("TAIWAN SEMICONDUCTOR ...").
    target = normalize_issuer(company).split()[:2]
    shares = value = 0.0
    for h in holdings:
        if h["put_call"]:
            continue
        if target and normalize_issuer(h["issuer"]).split()[:2] == target:
            shares += h["shares"]
            value += h["value"]
    return {"shares": shares, "value": value}


async def notable_fund_positions(company: str) -> Tuple[List[Dict], Dict]:
    """Which famous funds hold the company, and whether they added or trimmed last quarter."""
    async def one(fund):
        filings = await _fund_filings(fund["cik"])
        if not filings:
            return None
        latest = _match_position(await _fund_holdings(fund["cik"], filings[0]["acc"]), company)
        prior = (_match_position(await _fund_holdings(fund["cik"], filings[1]["acc"]), company)
                 if len(filings) > 1 else {"shares": 0.0, "value": 0.0})
        if latest["shares"] == 0 and prior["shares"] == 0:
            return None
        change = ((latest["shares"] - prior["shares"]) / prior["shares"] if prior["shares"]
                  else 1.0)
        return {"fund": fund["name"], "weight": fund["weight"], "shares": latest["shares"],
                "value": latest["value"], "change": round(change, 4), "as_of": filings[0]["date"],
                "url": SEC_FILING.format(cik=int(fund["cik"]), acc=filings[0]["acc"])}

    async def checked(fund):
        try:
            return await one(fund), True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"13F lookup failed for {fund['name']}: {e}")
            return None, False
    results = await asyncio.gather(*(checked(f) for f in NOTABLE_FUNDS))
    failed = sum(not ok for _, ok in results)
    status = {"status": "ok" if not failed else "partial" if failed < len(NOTABLE_FUNDS) else "failed",
              "provider": "SEC EDGAR (13F)",
              "detail": "13F holdings are filed up to 45 days after each quarter ends"}
    return [r for r, _ in results if isinstance(r, dict)], status


# ── Politicians (House/Senate disclosures) ──────────────────────────────────

def _amount_low(amount: str) -> float:
    nums = re.findall(r"[\d,]+", amount or "")
    return float(nums[0].replace(",", "")) if nums else 0.0


def _iso_date(d: str) -> str:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return ""


def parse_congress(rows: List[Dict], ticker: str, chamber: str) -> List[Dict]:
    out = []
    for r in rows:
        if (r.get("ticker") or "").upper() != ticker.upper():
            continue
        date = _iso_date(r.get("transaction_date", ""))
        if _days_ago(date) > LOOKBACK_DAYS_CONGRESS:
            continue
        kind = (r.get("type") or "").lower()
        side = "buy" if "purchase" in kind else "sell" if "sale" in kind else None
        if not side:
            continue
        out.append({
            "person": r.get("representative") or r.get("senator") or "Member of Congress",
            "role": f"Politician ({chamber.title()})", "side": side,
            "value": _amount_low(r.get("amount", "")), "amount_range": (r.get("amount") or "").strip(),
            "date": date,
            "source": f"{chamber.title()} disclosure", "url": r.get("ptr_link", ""),
        })
    return out


async def congress_trades(ticker: str) -> Tuple[List[Dict], Dict]:
    trades, chambers = [], {}
    for src in CONGRESS_SOURCES:
        body = await fetch_text(src["url"], max_age=12 * 3600, timeout=30)
        try:
            trades += parse_congress(json.loads(body), ticker, src["chamber"]) if body else []
            chambers[src["chamber"]] = "ok" if body else "failed"
        except (ValueError, TypeError):
            chambers[src["chamber"]] = "failed"
        if chambers[src["chamber"]] == "failed":
            logger.warning(f"{src['chamber'].title()} trade disclosures unavailable from {src['url']}")
    ok = sum(v == "ok" for v in chambers.values())
    status = {"status": "ok" if ok == len(chambers) else "failed" if ok == 0 else "partial",
              "provider": "House/Senate disclosure feeds", "chambers": chambers}
    return trades, status


# ── Scoring ─────────────────────────────────────────────────────────────────

def flow_score(trades: List[Dict], role_key: str = "role") -> Dict:
    """Role-weighted net buying in [-1, 1], plus a cluster flag (3+ different people buying)."""
    net = 0.0
    buyers = set()
    for t in trades:
        w = role_weight(t.get(role_key, ""))
        size = math.log10(1 + max(t.get("value", 0), 0)) / 6  # $1M ≈ 1.0
        if t["side"] == "buy":
            net += w * size
            buyers.add(t["person"])
        else:
            net -= w * size * SELL_DISCOUNT
    return {"score": math.tanh(net / 2), "buyers": len(buyers), "cluster_buying": len(buyers) >= 3,
            "trades": len(trades)}


def fund_score(positions: List[Dict]) -> float:
    total = sum(p["weight"] * max(-1.0, min(1.0, p["change"])) for p in positions)
    return math.tanh(total)


async def gather(ticker: str, company: Optional[Dict]) -> Dict:
    """All smart-money activity for one ticker."""
    unknown = ([], {"status": "failed", "detail": "ticker not found in the SEC company list"})
    insider_task = insider_trades(company["cik"]) if company else asyncio.sleep(0, result=unknown)
    fund_task = notable_fund_positions(company["name"]) if company else asyncio.sleep(0, result=unknown)
    results = await asyncio.gather(insider_task, fund_task, congress_trades(ticker), return_exceptions=True)

    def unpack(r, provider):
        if isinstance(r, tuple):
            return r
        logger.warning(f"{provider} lookup failed: {r}")
        return [], {"status": "failed", "provider": provider, "detail": "lookup error"}
    (insiders, s_ins), (funds, s_funds), (congress, s_con) = (
        unpack(results[0], "SEC EDGAR (Form 4)"), unpack(results[1], "SEC EDGAR (13F)"),
        unpack(results[2], "House/Senate disclosure feeds"))
    manual = [t for t in load_notable_trades() if t.get("ticker", "").upper() == ticker.upper()
              and _days_ago(t.get("date", "")) <= LOOKBACK_DAYS_INSIDERS]
    return {
        "insiders": insiders + manual,
        "funds": funds,
        "congress": congress,
        "insider_flow": flow_score(insiders + manual),
        "congress_flow": flow_score(congress),
        "fund_score": fund_score(funds),
        "sources": {"insiders": s_ins, "funds": s_funds, "congress": s_con},
    }
