"""Real addresses for Watch profiles, so search engines can index each one. /watch/nancy-pelosi
gets the directory page with that person's own title, description and canonical address."""
import html
import re
from typing import Dict, List, Optional

BASE = "https://lyraauth.com"
RESERVED = {"live", "account", "unsubscribe", "index.html"}


def url_for(pid: str) -> str:
    return f"{BASE}/watch/{pid}"


def blurb(rec: Dict) -> str:
    who = rec["name"] + (f", {rec['job']}" if rec.get("job") else "")
    return f"{who}: recent trades, statements, companies mentioned and news coverage, from public sources, on Lyra Watch."


def _meta_tag(page: str, pattern: str, replacement: str) -> str:
    return re.sub(pattern, lambda _: replacement, page, count=1)


def render(page: str, rec: Dict) -> str:
    """The directory page, labelled for one person. Text is escaped: names come from the news."""
    title = html.escape(f"{rec['name']} — Lyra Watch")
    desc = html.escape(blurb(rec), quote=True)
    url = html.escape(url_for(rec["id"]), quote=True)
    page = _meta_tag(page, r"<title>.*?</title>", f"<title>{title}</title>")
    page = _meta_tag(page, r'<meta name="description"[^>]*>', f'<meta name="description" content="{desc}" />')
    page = _meta_tag(page, r'<link rel="canonical"[^>]*>', f'<link rel="canonical" href="{url}" />')
    page = _meta_tag(page, r'<meta property="og:title"[^>]*>', f'<meta property="og:title" content="{title}" />')
    page = _meta_tag(page, r'<meta property="og:description"[^>]*>', f'<meta property="og:description" content="{desc}" />')
    page = _meta_tag(page, r'<meta property="og:url"[^>]*>', f'<meta property="og:url" content="{url}" />')
    mark = f'<meta name="lyra-person" content="{html.escape(rec["id"], quote=True)}" />'
    return page.replace("</head>", mark + "\n</head>", 1)


def sitemap(ids: List[str]) -> str:
    rows = "".join(f"<url><loc>{html.escape(url_for(i))}</loc><changefreq>daily</changefreq></url>" for i in sorted(set(ids)) if i)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'


def trades_of(profile: Optional[Dict], limit: int = 3) -> List[Dict]:
    moves = [m for m in (profile or {}).get("moves", []) if m.get("type") == "trade"]
    moves.sort(key=lambda m: m.get("date", ""), reverse=True)
    return [{k: m.get(k, "") for k in ("title", "date", "url")} for m in moves[:limit]]
