"""Fetching from PubChem and the NIST Chemistry WebBook, with a SQLite cache.

PubChem asks for at most 5 requests a second; NIST is a small public server.
Both are gated and every response is cached, so repeat lookups never reach them.
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.environ.get("LYRA_COSHH_DIR", ROOT / "data" / "coshh"))
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound"
NIST = "https://webbook.nist.gov/cgi/cbook.cgi"
USER_AGENT = "LyraCOSHH/1.0 (+https://lyraauth.com/coshh/)"

# The PUG-View headings a safety data sheet is built from. Fetched one by one
# because a whole record can be tens of megabytes of literature and patents.
HEADINGS = ["Safety and Hazards", "Toxicity", "Experimental Properties", "Spectral Information",
            "Regulatory Information", "Other Identifiers", "Use and Manufacturing"]

DAY = 86400
_gates = {"pubchem": asyncio.Semaphore(4), "nist": asyncio.Semaphore(2)}


class _Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, at REAL, body TEXT)")
        self._lock = threading.Lock()

    def get(self, key: str, max_age: float) -> Optional[str]:
        with self._lock:
            row = self._db.execute("SELECT at, body FROM cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < max_age:
            return row[1]
        return None

    def put(self, key: str, body: str):
        with self._lock:
            self._db.execute("REPLACE INTO cache VALUES (?,?,?)", (key, time.time(), body))
            self._db.commit()


_cache: Optional[_Cache] = None


def cache() -> _Cache:
    global _cache
    if _cache is None:
        _cache = _Cache(DATA_DIR / "cache.db")
    return _cache


class NotFound(Exception):
    pass


async def _get(url: str, gate: str, max_age: float, timeout: float = 30) -> Optional[str]:
    """GET a URL through the cache. Returns None for 404, raises on other failures.
    A 404 is cached too (as an empty body), so missing records aren't re-asked."""
    hit = cache().get(url, max_age)
    if hit is not None:
        return hit or None
    for attempt in range(3):
        async with _gates[gate]:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                         headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(url)
            if gate == "pubchem":
                await asyncio.sleep(0.2)
        # PubChem answers 503 "ServerBusy" under load; back off and retry.
        if resp.status_code not in (429, 503):
            break
        await asyncio.sleep(1.5 * (attempt + 1))
    if resp.status_code == 404 or (gate == "nist" and resp.status_code == 200 and "##TITLE" not in resp.text):
        cache().put(url, "")
        return None
    resp.raise_for_status()
    cache().put(url, resp.text)
    return resp.text


async def autocomplete(q: str, limit: int = 10) -> List[str]:
    body = await _get(f"https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound/{quote(q, safe='')}/json?limit={limit}",
                      "pubchem", 7 * DAY, timeout=10)
    if not body:
        return []
    return json.loads(body).get("dictionary_terms", {}).get("compound", [])


async def resolve(q: str) -> int:
    """PubChem CID for a name, synonym or CAS number."""
    q = q.strip()
    if q.isdigit():
        return int(q)
    body = await _get(f"{PUG}/compound/name/{quote(q, safe='')}/cids/JSON", "pubchem", 30 * DAY, timeout=15)
    if not body:
        raise NotFound(q)
    cids = json.loads(body).get("IdentifierList", {}).get("CID") or []
    if not cids:
        raise NotFound(q)
    return int(cids[0])


async def properties(cid: int) -> dict:
    body = await _get(f"{PUG}/compound/cid/{cid}/property/Title,IUPACName,MolecularFormula,MolecularWeight,"
                      f"InChIKey,SMILES/JSON", "pubchem", 30 * DAY, timeout=15)
    if not body:
        raise NotFound(str(cid))
    return json.loads(body)["PropertyTable"]["Properties"][0]


async def record_parts(cid: int) -> Tuple[Dict[str, Optional[dict]], List[str]]:
    """The PUG-View record for each heading in HEADINGS (None where PubChem has nothing),
    and the headings that couldn't be fetched right now."""
    failed: List[str] = []

    async def one(h):
        try:
            body = await _get(f"{PUG_VIEW}/{cid}/JSON?heading={quote(h)}", "pubchem", 7 * DAY)
        except httpx.HTTPError as e:
            logger.warning(f"PubChem {cid} {h}: {e}")
            failed.append(h)
            return h, None
        return h, (json.loads(body)["Record"] if body else None)
    parts = dict(await asyncio.gather(*(one(h) for h in HEADINGS)))
    if "Safety and Hazards" in failed:
        raise httpx.HTTPError("PubChem safety data unavailable")
    return parts, failed


CAS_RE = re.compile(r"^\d{2,7}-\d\d-\d$")


async def nist_jcamp(cas: str, kind: str, index: int = 0) -> Optional[str]:
    """A JCAMP-DX spectrum from the NIST WebBook: kind 'IR' or 'Mass'."""
    if not CAS_RE.match(cas) or kind not in ("IR", "Mass") or not 0 <= index < 20:
        raise ValueError("bad spectrum request")
    return await _get(f"{NIST}?JCAMP=C{cas.replace('-', '')}&Index={index}&Type={kind}", "nist", 90 * DAY)
