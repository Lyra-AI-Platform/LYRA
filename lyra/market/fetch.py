"""Shared HTTP fetching with a SQLite-backed cache so repeated scans
don't hammer the SEC, Yahoo or news sites."""
import asyncio
import logging
from typing import Optional

import httpx

from lyra.market.config import BROWSER_USER_AGENT, SEC_USER_AGENT
from lyra.market.store import get_store

logger = logging.getLogger(__name__)

# SEC allows 10 requests/second; stay well under it.
_sec_gate = asyncio.Semaphore(4)


def _headers(url: str) -> dict:
    ua = SEC_USER_AGENT if "sec.gov" in url else BROWSER_USER_AGENT
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


async def fetch_text(url: str, max_age: float = 900, timeout: float = 15) -> Optional[str]:
    """GET a URL, returning the body or None. Responses are cached for max_age seconds."""
    store = get_store()
    cached = store.cache_get(url, max_age)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_headers(url)) as client:
            if "sec.gov" in url:
                async with _sec_gate:
                    resp = await client.get(url)
                    await asyncio.sleep(0.15)
            else:
                resp = await client.get(url)
        if resp.status_code != 200:
            logger.debug(f"GET {url} -> {resp.status_code}")
            return None
        store.cache_put(url, resp.text)
        return resp.text
    except Exception as e:
        logger.debug(f"GET {url} failed: {e}")
        return None
