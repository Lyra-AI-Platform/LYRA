"""
LyraAuth request checks that need no database: which site a browser request came from, and
reading a siteverify body. Kept apart from the routes so they can be tested on their own.
"""
import hashlib
import hmac
import json
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlsplit

DEV_HOSTS = ("localhost", "127.0.0.1")


def host_of(url: str) -> str:
    """The lower-case host of a URL, or "" if there isn't one ("null" origins have none)."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def origin_allowed(domain: str, origin: Optional[str], referer: Optional[str]) -> bool:
    """
    May this page use a site registered for `domain`? Subdomains count, and www is ignored.
    A site with no domain on file accepts any origin, so keys made before domains were
    required keep working. Local hosts are allowed for development.
    A non-browser client can fake these headers: this stops a key being lifted onto another
    website. It does not replace the secret key check in siteverify.
    """
    domain = (domain or "").strip().lower()
    domain = domain[4:] if domain.startswith("www.") else domain
    if not domain:
        return True
    host = host_of(origin or "") or host_of(referer or "")
    return host in DEV_HOSTS or host == domain or host.endswith("." + domain)


def solved_on(origin: Optional[str], referer: Optional[str]) -> str:
    """The hostname the widget was running on, for siteverify's "hostname" field."""
    return host_of(origin or "") or host_of(referer or "")


HASH_PREFIX = "sha256:"


def is_hashed(stored: str) -> bool:
    return (stored or "").startswith(HASH_PREFIX)


def hash_secret(secret: str) -> str:
    """Secret keys are long and random, so one round of SHA-256 is enough at rest. It also gives
    a stable value to look a site up by, which a salted password hash wouldn't."""
    return HASH_PREFIX + hashlib.sha256(secret.encode()).hexdigest()


def secret_matches(stored: str, given: str) -> bool:
    return hmac.compare_digest(stored or "", hash_secret(given))


def parse_siteverify(body: bytes, content_type: str) -> Tuple[str, str]:
    """
    (secret, token) from a siteverify body. JSON is the documented form. Form-encoded bodies
    and reCAPTCHA's field names (secret, response) also work, so a migration is a URL change.
    """
    data: dict = {}
    if "application/x-www-form-urlencoded" in (content_type or "").lower():
        data = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
    else:
        try:
            parsed = json.loads(body or b"{}")
            data = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            data = {}
    secret = data.get("secret_key") or data.get("secret") or ""
    token = data.get("token") or data.get("response") or ""
    return (secret, token) if isinstance(secret, str) and isinstance(token, str) else ("", "")
