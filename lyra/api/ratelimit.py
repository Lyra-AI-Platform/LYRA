"""Small in-memory rate limits for sign-in, sign-up and other abuse-prone routes.

One process serves the site, so counters in memory are enough. Behind Cloudflare the
visitor's address is in CF-Connecting-IP (Cloudflare overwrites any value a client sends).
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, Request

_hits: Dict[str, Deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def check(key: str, limit: int, window: float, record: bool = True) -> None:
    """429 when `key` already has `limit` hits inside `window` seconds; otherwise counts one."""
    now, q = time.time(), _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        retry = int(window - (now - q[0])) + 1
        raise HTTPException(429, f"Too many attempts. Try again in {max(retry // 60, 1)} minute(s).",
                            headers={"Retry-After": str(retry)})
    if record:
        q.append(now)


def record(key: str) -> None:
    _hits[key].append(time.time())


def reset() -> None:
    _hits.clear()
