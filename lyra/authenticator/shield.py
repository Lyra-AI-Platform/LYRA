"""
LyraAuth bot defences that sit around every challenge.

Each check here is decided by the server, not by numbers the browser reports:

  Proof of work   Every challenge carries a random salt and a difficulty. The browser must find a
                  nonce whose SHA-256(salt + nonce) starts with that many zero bits. A person never
                  notices (it runs while they read the question); a farm solving thousands of
                  challenges pays for every one. The same idea as ALTCHA and Friendly Captcha.
  Server timing   How long the answer took is measured from when the server issued the challenge.
                  The browser's own figure is only used to spot a story that doesn't add up.
  Graded answers  Only challenges with a right answer can pass someone. Opinion questions still
                  collect training data, but can't open the door on their own.
  Back-off        An IP that keeps failing gets harder proof of work, up to a ceiling, and the
                  difficulty drops again once it stops.
  Signals         Automation flags the browser can't easily hide (navigator.webdriver, no pointer
                  or keyboard input at all) lower the score the site receives.

The score sent to the site (0.0 to 1.0) works like reCAPTCHA v3's: sites can set their own bar.
"""
import hashlib
import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

POW_BASE_BITS = 15          # about 33,000 hashes: well under a second in a browser
POW_MAX_BITS = 21           # about 2 million: several seconds, only after repeated failures
POW_STEP_PER_FAILURE = 1
FAILURE_WINDOW_S = 15 * 60
MIN_HUMAN_SECONDS = 1.2     # nobody reads a question and picks an answer faster than this
MAX_ANSWER_SECONDS = 300
CLOCK_SLACK_S = 5.0         # the browser may not claim to have taken longer than the server saw
PASS_SCORE = 0.6
# Widgets cached before 1.3.0 send no proof of work. Until this moment they still pass, scored
# lower, so a visitor with an old copy isn't locked out while caches refresh. After it, never.
LEGACY_UNTIL = 1794211200   # 2026-11-09 08:00 UTC


def new_salt() -> str:
    return secrets.token_hex(12)


def leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def pow_ok(salt: str, nonce, bits: int) -> bool:
    """True when SHA-256(salt + str(nonce)) starts with at least `bits` zero bits."""
    if nonce is None or bits <= 0:
        return bits <= 0
    try:
        n = int(nonce)
    except (TypeError, ValueError):
        return False
    if n < 0 or n > 2 ** 40:
        return False
    return leading_zero_bits(hashlib.sha256(f"{salt}{n}".encode()).digest()) >= bits


def solve_pow(salt: str, bits: int, limit: int = 2 ** 26) -> Optional[int]:
    """Reference solver, used by the tests."""
    for n in range(limit):
        if pow_ok(salt, n, bits):
            return n
    return None


class FailureLog:
    """Recent failures per client, kept in memory with a sliding window."""

    def __init__(self, window_s: float = FAILURE_WINDOW_S, cap: int = 50):
        self.window_s = window_s
        self.cap = cap
        self._log: Dict[str, Deque[float]] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> Deque[float]:
        q = self._log[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if not q:
            self._log.pop(key, None)
        return q

    def record(self, key: str, now: Optional[float] = None) -> None:
        if not key:
            return
        now = now or time.time()
        q = self._log[key]
        q.append(now)
        while len(q) > self.cap:
            q.popleft()

    def count(self, key: str, now: Optional[float] = None) -> int:
        if not key:
            return 0
        return len(self._trim(key, now or time.time()))

    def clear(self, key: str) -> None:
        self._log.pop(key, None)


def difficulty_for(failures: int) -> int:
    return min(POW_MAX_BITS, POW_BASE_BITS + POW_STEP_PER_FAILURE * max(0, failures))


def score(*, correct: bool, graded: bool, pow_passed: bool, issued_at: float, now: float,
          claimed_ms: int, signals: Optional[dict] = None) -> Tuple[float, str]:
    """
    How sure we are this was a person, and why not when it fails.
    Returns (score, reason). reason is "" when the attempt passes.
    """
    signals = signals or {}
    elapsed = now - issued_at
    legacy = signals.get("legacy_widget") and now < LEGACY_UNTIL
    if not pow_passed and not legacy:
        return 0.0, "proof-of-work"
    if elapsed < MIN_HUMAN_SECONDS:
        return 0.0, "too-fast"
    if elapsed > MAX_ANSWER_SECONDS:
        return 0.0, "expired"
    if not graded:
        return 0.0, "ungraded"
    if not correct:
        return 0.1, "wrong-answer"

    s = 0.8 if not legacy else 0.65
    # A story that doesn't add up: the browser says it took far longer than the server saw.
    if claimed_ms and claimed_ms / 1000.0 > elapsed + CLOCK_SLACK_S:
        s -= 0.25
    if 1.5 <= elapsed <= 60:
        s += 0.1
    if signals.get("webdriver"):
        s -= 0.45
    if signals.get("interacted") is False:
        s -= 0.2
    elif signals.get("interacted"):
        s += 0.05
    if signals.get("headless"):
        s -= 0.3
    s = max(0.0, min(1.0, round(s, 2)))
    return s, ("" if s >= PASS_SCORE else "low-score")
