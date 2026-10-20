"""Signed-in sessions.

A sign-in creates a LoginSession row and puts a random ID in the lyra_session cookie:

  HttpOnly   page scripts can't read it, so a script injected into a page can't steal it
  Secure     only sent over https (LYRA_INSECURE_COOKIES=1 for plain-http local testing)
  SameSite   Lax: other sites can link here, but their forms and scripts don't carry it

Only a hash of the ID is stored. A session ends after IDLE without use or ABSOLUTE after
sign-in, whichever comes first, and can be ended early from any other signed-in browser.

Requests that change something (anything but GET/HEAD/OPTIONS) must also come from this
site's own pages (same_origin), which stops cross-site request forgery. The lyra_in cookie is
a plain marker the page scripts can see; it says nothing about who is signed in.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union
from urllib.parse import urlsplit

from fastapi import Request, Response, WebSocket
from sqlalchemy.orm import Session

from lyra.db.models import LoginSession, User

COOKIE = "lyra_session"
MARKER = "lyra_in"
IDLE = timedelta(days=14)
ABSOLUTE = timedelta(days=30)
TOUCH = timedelta(minutes=10)      # how stale last_seen may get before it's rewritten
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

Conn = Union[Request, WebSocket]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone=True columns.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _secure() -> bool:
    return os.getenv("LYRA_INSECURE_COOKIES") != "1"


def _client_ip(conn: Conn) -> str:
    return conn.headers.get("cf-connecting-ip") or (conn.client.host if conn.client else "")


def set_cookies(response: Response, token: str) -> None:
    age = int(ABSOLUTE.total_seconds())
    response.set_cookie(COOKIE, token, max_age=age, httponly=True, secure=_secure(), samesite="lax", path="/")
    response.set_cookie(MARKER, "1", max_age=age, httponly=False, secure=_secure(), samesite="lax", path="/")


def clear_cookies(response: Response) -> None:
    for name in (COOKIE, MARKER):
        response.delete_cookie(name, path="/", secure=_secure(), samesite="lax")


def start(db: Session, user: User, conn: Request, response: Response) -> LoginSession:
    """Sign `user` in on this browser. Always a fresh ID, so an ID planted before sign-in
    (session fixation) is worthless; the browser's previous session, if any, is ended."""
    old = conn.cookies.get(COOKIE)
    if old:
        db.query(LoginSession).filter(LoginSession.token_hash == _hash(old)).delete()
    token = secrets.token_urlsafe(32)
    now = _now()
    row = LoginSession(user_id=user.id, token_hash=_hash(token), created_at=now, last_seen=now,
                       expires_at=now + ABSOLUTE, ip=_client_ip(conn)[:64],
                       user_agent=(conn.headers.get("user-agent") or "")[:200])
    db.add(row)
    db.commit()
    set_cookies(response, token)
    return row


def current(conn: Conn, db: Session) -> Optional[Tuple[LoginSession, User]]:
    """The live session and its user for this browser, or None."""
    token = conn.cookies.get(COOKIE)
    if not token or len(token) > 100:
        return None
    row = db.query(LoginSession).filter(LoginSession.token_hash == _hash(token)).first()
    if not row:
        return None
    now = _now()
    if _aware(row.expires_at) <= now or now - _aware(row.last_seen) > IDLE:
        db.delete(row)
        db.commit()
        return None
    user = db.query(User).filter(User.id == row.user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        return None
    if now - _aware(row.last_seen) > TOUCH:
        row.last_seen = now
        db.commit()
    return row, user


def user_from_cookie(conn: Conn, db: Session) -> Optional[User]:
    found = current(conn, db)
    return found[1] if found else None


def end(db: Session, conn: Conn, response: Optional[Response] = None) -> None:
    token = conn.cookies.get(COOKIE)
    if token:
        db.query(LoginSession).filter(LoginSession.token_hash == _hash(token)).delete()
        db.commit()
    if response is not None:
        clear_cookies(response)


def end_all(db: Session, user_id: int, keep: Optional[int] = None) -> int:
    """End every session of a user (except `keep`, a LoginSession id). Returns how many."""
    q = db.query(LoginSession).filter(LoginSession.user_id == user_id)
    if keep is not None:
        q = q.filter(LoginSession.id != keep)
    n = q.delete()
    db.commit()
    return n


def _allowed_origins(conn: Conn) -> set:
    own = {f"https://{conn.headers.get('host', '')}", f"http://{conn.headers.get('host', '')}"}
    extra = os.getenv("LYRA_PUBLIC_ORIGINS", "https://lyraauth.com,https://www.lyraauth.com")
    return own | {o.strip().rstrip("/") for o in extra.split(",") if o.strip()}


def same_origin(conn: Conn, strict: bool = False) -> bool:
    """Did this request come from one of this site's own pages? Browsers always say where a
    POST or a WebSocket comes from (Origin, or Sec-Fetch-Site). A request with neither isn't
    from a browser, so it can't be a forged one; `strict` refuses it anyway (WebSockets)."""
    origin = conn.headers.get("origin")
    if origin:
        parts = urlsplit(origin)
        return f"{parts.scheme}://{parts.netloc}" in _allowed_origins(conn)
    site = conn.headers.get("sec-fetch-site")
    if site:
        return site in ("same-origin", "none")
    return not strict
