"""Which pages need what, checked on the server before any HTML is sent.

The page scripts also check, but a script runs after the page has arrived, so on its own it
can be skipped (view-source, curl, scripts off). Here the page itself is withheld:

  public    marketing, docs, legal, pricing: anyone
  account   signed in (dashboard, billing)
  member    signed in with a paid plan or a trial that hasn't run out (the products)
  watch     signed in with Lyra Watch Pro or any paid plan (Watch Live)
  owner     the site owner only (LYRA_ADMIN_EMAILS); everyone else gets a plain 404
  unlisted  anyone holding the link, but never linked from the site or listed by search engines

Sign-in comes from the session cookie (lyra/api/sessions.py). Only GET/HEAD
are checked here; the APIs still check the bearer token and trial allowances themselves.
"""
import posixpath
import re
from typing import Optional, Tuple
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from lyra.api import entitlements
from lyra.api import sessions
from lyra.api.users_api import _admin_emails
from lyra.db.database import SessionLocal
from lyra.db.models import User

LOGIN = "/dashboard/login.html"
# A path on this site only: never "//other.site", a backslash trick or a full URL.
SAFE_NEXT = re.compile(r"^/(?![/\\])[A-Za-z0-9\-._~/?=&%+]*$")
SIGNUP = "/dashboard/register.html"

# (path prefix, rule, feature name for the upgrade page). A prefix ending in "/" covers the
# folder; anything else must match exactly. The first match wins, so list specific ones first.
RULES: Tuple[Tuple[str, str, str], ...] = (
    ("/dashboard/login.html", "guest", ""),
    ("/dashboard/register.html", "guest", ""),
    ("/home/", "account", ""),
    ("/account/", "account", ""),
    ("/account", "account", ""),
    ("/home", "account", ""),
    ("/dashboard/chat.html", "member", "chat"),
    ("/dashboard/", "account", ""),
    ("/dashboard", "account", ""),
    ("/market", "member", "market"),
    ("/coshh/", "member", "coshh"),
    ("/coshh", "member", "coshh"),
    ("/api/coshh/", "member", "coshh"),
    ("/watch/live/", "watch", "watch_live"),
    ("/watch/live", "watch", "watch_live"),
    # FuelTrack's App Store privacy policy: the App Store links to it, Lyra pages don't.
    # /fuelwise/privacy/ is its old address and now just redirects to the new one.
    ("/fueltrack/privacy/", "unlisted", ""),
    ("/fueltrack/privacy", "unlisted", ""),
    ("/fuelwise/privacy/", "unlisted", ""),
    ("/fuelwise/privacy", "unlisted", ""),
    # Privacy policies the App Store links to for the Lyra Labs iPhone apps.
    ("/hushhub/privacy/", "unlisted", ""),
    ("/hushhub/privacy", "unlisted", ""),
    ("/regulatrack/privacy/", "unlisted", ""),
    ("/regulatrack/privacy", "unlisted", ""),
    ("/designdocket/privacy/", "unlisted", ""),
    ("/designdocket/privacy", "unlisted", ""),
    ("/dataguard/privacy/", "unlisted", ""),
    ("/dataguard/privacy", "unlisted", ""),
    ("/transitaid/privacy/", "unlisted", ""),
    ("/transitaid/privacy", "unlisted", ""),
    ("/collectorshaven/privacy/", "unlisted", ""),
    ("/collectorshaven/privacy", "unlisted", ""),
    ("/admin/", "owner", ""),
    ("/admin", "owner", ""),
    ("/fueltrack/", "owner", ""),
    ("/fueltrack", "owner", ""),
    ("/fuelwise/", "owner", ""),
    ("/fuelwise", "owner", ""),
)


session_factory = SessionLocal   # tests point this at a throwaway database


def _normal(path: str) -> str:
    """The path as the file server will resolve it: "//coshh/", "/x/../coshh/" and "/COSHH/"
    must all meet the rule for "/coshh/"."""
    clean = posixpath.normpath(re.sub(r"/+", "/", path or "/")).lower()
    return clean + "/" if path.endswith("/") and clean != "/" else clean


def rule_for(path: str) -> Optional[Tuple[str, str]]:
    path = _normal(path)
    for prefix, rule, feature in RULES:
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
            return rule, feature
    return None


def is_member(user: User) -> bool:
    return entitlements.is_paid(user) or entitlements.trial_days_left(user) > 0


def _target(request: Request) -> str:
    q = request.url.query
    return request.url.path + (f"?{q}" if q else "")


def _deny(request: Request, location: str, api: bool, status: int, reason: str):
    if api:
        return JSONResponse({"detail": {"error": reason, "upgrade_url": location}}, status_code=status,
                            headers={"Cache-Control": "no-store"})
    return RedirectResponse(location, status_code=303, headers={"Cache-Control": "no-store"})


def check(request: Request):
    """None to let the request through, otherwise the redirect / error to send instead."""
    if request.method not in ("GET", "HEAD"):
        return None
    path = _normal(request.url.path)
    found = rule_for(path)
    if not found:
        return None
    rule, feature = found
    if rule == "unlisted":
        return None
    api = path.startswith("/api/")
    db = session_factory()
    try:
        user = sessions.user_from_cookie(request, db)
        # A session ended elsewhere (sign out everywhere, password change, expiry) leaves its
        # cookie behind; clear it so the page scripts stop thinking they're signed in.
        request.state.stale_session = not user and bool(request.cookies.get(sessions.COOKIE))
        if rule == "guest":
            # Already signed in: skip the sign-in form and go where it was going to send them.
            if not user:
                return None
            nxt = request.query_params.get("next", "")
            return RedirectResponse(nxt if SAFE_NEXT.match(nxt) else "/", status_code=303)
        if rule == "owner":
            if user and user.email.lower() in _admin_emails():
                return None
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if not user:
            return _deny(request, f"{LOGIN}?next={quote(_target(request), safe='/')}", api, 401, "sign_in_required")
        if rule == "account":
            return None
        if rule == "member" and not is_member(user):
            return _deny(request, f"/dashboard/billing.html?need={feature}", api, 402, "payment_required")
        if rule == "watch":
            from lyra.api.watch_access import has_watch
            if not has_watch(user, db):
                return _deny(request, "/watch/account/?need=watch", api, 402, "payment_required")
        return None
    finally:
        db.close()


async def guard(request: Request, call_next):
    """HTTP middleware: apply RULES before the page (or API) runs."""
    if not rule_for(request.url.path):
        return await call_next(request)
    response = check(request) or await call_next(request)
    if getattr(request.state, "stale_session", False):
        sessions.clear_cookies(response)
    # Never let a browser or Cloudflare keep a copy of a members-only page.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Vary"] = "Cookie"
    # Following a link out of an unlisted page mustn't tell the other site where it was.
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def signed_in_home(request: Request, website_dir) -> Optional[FileResponse]:
    """The home page a signed-in visitor gets at "/" instead of the marketing page."""
    db = session_factory()
    try:
        user = sessions.user_from_cookie(request, db)
    finally:
        db.close()
    if not user:
        if not request.cookies.get(sessions.COOKIE):
            return None
        public = FileResponse(str(website_dir / "index.html"), headers={"Cache-Control": "no-store"})
        sessions.clear_cookies(public)
        return public
    return FileResponse(str(website_dir / "home" / "index.html"),
                        headers={"Cache-Control": "no-store", "Vary": "Cookie"})
