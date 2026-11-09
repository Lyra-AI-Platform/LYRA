"""Google AdSense on lyraauth.com: on for the account in PUBLISHER (override or switch off with LYRA_ADSENSE_CLIENT), with the ad
unit's ID in LYRA_ADSENSE_SLOT (AdSense → Ads → By ad unit → Display ad, "Responsive").

When set:
  - /ads.txt names Google as an authorised seller for that publisher ID
  - every public page gets the account tag, so Google can verify the site
  - only Watch, Newswire and Tremor load the AdSense script and show at most ONE labelled unit, in
    the same box a sponsor would use (lyra/api/ads_api.py), and only when no sponsor is live
  - the page security policy allows Google's ad servers (and only while ads are on)

Keep Auto ads OFF in AdSense (Ads → By site → lyraauth.com): Auto ads add pop-ups, sticky bars
and ads in the middle of text, which is exactly what this site doesn't want. The homepage and
LyraAuth's own pages never load Google's script: they promise no ad tracking.

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
SCRIPT_PREFIXES = ("/watch", "/news", "/tremor")   # the pages with an ad box; the rest get the tag only
NO_ADS_PREFIXES = ("/admin", "/account", "/home", "/dashboard", "/labs", "/feedback", "/fuelwise", "/watch/account")
CLIENT_RE = re.compile(r"^ca-pub-\d{10,20}$")


PUBLISHER = "ca-pub-4940586207754938"   # Lyra Ventures Ltd's AdSense account; LYRA_ADSENSE_CLIENT=off turns ads off


def client() -> Optional[str]:
    c = os.getenv("LYRA_ADSENSE_CLIENT", PUBLISHER).strip()
    return c if CLIENT_RE.match(c) else None


def unit() -> Optional[dict]:
    """The one display unit pages may show, or None when AdSense is off or has no unit ID."""
    c, slot = client(), os.getenv("LYRA_ADSENSE_SLOT", "").strip()
    return {"client": c, "slot": slot} if c and slot.isdigit() else None


def ads_txt() -> Optional[str]:
    c = client()
    return f"google.com, {c.replace('ca-', '')}, DIRECT, {GOOGLE_TAG}\n" if c else None


def csp_extra() -> str:
    """Added to script-src, connect-src and frame-src when ads are on."""
    return AD_HOSTS if client() else ""


def wants_ads(path: str) -> bool:
    p = path.lower()
    return bool(client()) and not any(p.startswith(x) for x in NO_ADS_PREFIXES)


def loads_script(path: str) -> bool:
    return bool(unit()) and path.lower().startswith(SCRIPT_PREFIXES)


def head_tags(script: bool = True) -> bytes:
    c = client()
    tag = f'<meta name="google-adsense-account" content="{c}" />\n'
    if not script:
        return tag.encode()
    return (tag + f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={c}" '
            f'crossorigin="anonymous"></script>\n').encode()


def ad_free(request, db) -> bool:
    """Signed in on a paid plan or Watch Pro: no ads."""
    from lyra.api import entitlements
    from lyra.api.watch_access import has_watch
    user = entitlements.user_from_conn(request, db)
    return bool(user and (entitlements.is_paid(user) or has_watch(user, db)))
