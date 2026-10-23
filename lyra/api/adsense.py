"""Google AdSense on lyraauth.com: switched on by one setting, LYRA_ADSENSE_CLIENT (ca-pub-…).

When set:
  - /ads.txt names Google as an authorised seller for that publisher ID
  - public pages get the AdSense account tag and the Auto ads script in <head>, so Google can
    verify the site and place ads itself
  - the page security policy allows Google's ad servers (and only while ads are on)

Never shown: member pages, the admin and account pages, and anyone on a paid plan or Watch Pro
(both promise ad-free). Consent for visitors in the UK and EEA comes from Google's own
certified consent message, switched on in AdSense → Privacy & messaging.
"""
import os
import re
from typing import Optional

GOOGLE_TAG = "f08c47fec0942fa0"   # Google's certification authority ID, the same for every publisher
AD_HOSTS = ("https://pagead2.googlesyndication.com https://*.googlesyndication.com https://*.doubleclick.net "
            "https://*.google.com https://*.gstatic.com https://fundingchoicesmessages.google.com https://*.adtrafficquality.google")
NO_ADS_PREFIXES = ("/admin", "/account", "/home", "/dashboard", "/labs", "/feedback", "/fuelwise", "/watch/account")
CLIENT_RE = re.compile(r"^ca-pub-\d{10,20}$")


def client() -> Optional[str]:
    c = os.getenv("LYRA_ADSENSE_CLIENT", "").strip()
    return c if CLIENT_RE.match(c) else None


def ads_txt() -> Optional[str]:
    c = client()
    return f"google.com, {c.replace('ca-', '')}, DIRECT, {GOOGLE_TAG}\n" if c else None


def csp_extra() -> str:
    """Added to script-src, connect-src and frame-src when ads are on."""
    return AD_HOSTS if client() else ""


def wants_ads(path: str) -> bool:
    p = path.lower()
    return bool(client()) and not any(p.startswith(x) for x in NO_ADS_PREFIXES)


def head_tags() -> bytes:
    c = client()
    return (f'<meta name="google-adsense-account" content="{c}" />\n'
            f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={c}" '
            f'crossorigin="anonymous"></script>\n').encode()


def ad_free(request, db) -> bool:
    """Signed in on a paid plan or Watch Pro: no ads."""
    from lyra.api import entitlements
    from lyra.api.watch_access import has_watch
    user = entitlements.user_from_conn(request, db)
    return bool(user and (entitlements.is_paid(user) or has_watch(user, db)))
