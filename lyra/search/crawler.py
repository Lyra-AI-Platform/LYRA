"""
NEXUS Autonomous Web Crawler
Crawls web pages, Wikipedia, RSS feeds, and extracts clean knowledge.
Used by the auto-learner background system.
"""
import asyncio
import hashlib
import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urljoin, quote

logger = logging.getLogger(__name__)


class NexusCrawler:
    """
    Multi-source web crawler for autonomous knowledge gathering.
    Sources: Wikipedia, RSS feeds, DuckDuckGo results, direct URLs.
    """

    # Domains that are high-quality knowledge sources
    TRUSTED_DOMAINS = {
        "en.wikipedia.org",
        "developer.mozilla.org",
        "docs.python.org",
        "arxiv.org",
        "github.com",
        "stackoverflow.com",
        "medium.com",
        "news.ycombinator.com",
    }

    # RSS feeds for auto news ingestion
    DEFAULT_RSS_FEEDS = [
        "https://news.ycombinator.com/rss",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://rss.arxiv.org/rss/cs.AI",
        "https://rss.arxiv.org/rss/cs.LG",
    ]

    def __init__(self):
        self._visited: set = set()
        self._session = None

    async def crawl_topic(self, topic: str, depth: int = 1) -> List[Dict[str, Any]]:
        """
        Crawl the web for a topic. Returns list of knowledge chunks.
        depth=1: just search results
        depth=2: search results + follow links within results
        """
        results = []

        # 1. Wikipedia (highest quality, always first)
        wiki = await self.crawl_wikipedia(topic)
        if wiki:
            results.append(wiki)

        # 2. DuckDuckGo results
        search_results = await self.search_and_crawl(topic, max_pages=3)
        results.extend(search_results)

        logger.info(f"Crawled topic '{topic}': {len(results)} chunks")
        return results

    async def crawl_wikipedia(self, topic: str) -> Optional[Dict[str, Any]]:
        """Fetch a Wikipedia article for a topic."""
        try:
            import httpx
            search_url = (
                f"https://en.wikipedia.org/w/api.php"
                f"?action=query&list=search&srsearch={quote(topic)}"
                f"&format=json&srlimit=1"
            )
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(search_url, headers={"User-Agent": "NEXUS-AI/1.0"})
                data = resp.json()

                search_results = data.get("query", {}).get("search", [])
                if not search_results:
                    return None

                page_title = search_results[0]["title"]

                # Fetch full article content
                content_url = (
                    f"https://en.wikipedia.org/w/api.php"
                    f"?action=query&titles={quote(page_title)}"
                    f"&prop=extracts&exintro=false&explaintext=true"
                    f"&exsectionformat=plain&format=json"
                )
                resp2 = await client.get(content_url, headers={"User-Agent": "NEXUS-AI/1.0"})
                data2 = resp2.json()

                pages = data2.get("query", {}).get("pages", {})
                page = next(iter(pages.values()))
                extract = page.get("extract", "")

                if not extract or len(extract) < 100:
                    return None

                # Chunk into sections (Wikipedia can be huge)
                chunks = self._chunk_text(extract, max_chars=3000)
                main_chunk = chunks[0] if chunks else extract[:3000]

                return {
                    "source": "wikipedia",
                    "title": page_title,
                    "url": f"https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}",
                    "content": main_chunk,
                    "topic": topic,
                    "quality": "high",
                    "full_chunks": chunks,
                }
        except Exception as e:
            logger.debug(f"Wikipedia crawl failed for '{topic}': {e}")
            return None

    async def search_and_crawl(
        self, topic: str, max_pages: int = 3
    ) -> List[Dict[str, Any]]:
        """Search DuckDuckGo and crawl top results."""
        results = []
        try:
            from duckduckgo_search import DDGS

            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(topic, max_results=max_pages + 2))

            raw = await loop.run_in_executor(None, _search)

            for item in raw[:max_pages]:
                url = item.get("href", "")
                if not url or self._is_visited(url):
                    continue

                content = await self._fetch_clean(url)
                if content and len(content) > 200:
                    results.append({
                        "source": "web",
                        "title": item.get("title", url),
                        "url": url,
                        "content": content[:3000],
                        "snippet": item.get("body", "")[:300],
                        "topic": topic,
                        "quality": "medium",
                    })
                    self._mark_visited(url)

        except ImportError:
            logger.warning("duckduckgo-search not available for auto-learning")
        except Exception as e:
            logger.debug(f"Search crawl failed: {e}")

        return results

    async def crawl_rss_feeds(
        self, feeds: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Crawl RSS feeds for fresh news/articles."""
        feeds = feeds or self.DEFAULT_RSS_FEEDS
        results = []

        for feed_url in feeds:
            try:
                items = await self._parse_rss(feed_url)
                results.extend(items)
            except Exception as e:
                logger.debug(f"RSS fetch failed {feed_url}: {e}")

        return results

    async def _parse_rss(self, url: str) -> List[Dict[str, Any]]:
        """Parse an RSS feed and return items."""
        try:
            import httpx
            from xml.etree import ElementTree as ET

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers={"User-Agent": "NEXUS-AI/1.0"})
                root = ET.fromstring(resp.text)

            items = []
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # Handle both RSS and Atom
            entries = root.findall(".//item") or root.findall(".//atom:entry", ns)

            for entry in entries[:10]:
                title_el = entry.find("title")
                link_el = entry.find("link")
                desc_el = entry.find("description") or entry.find("summary")

                title = title_el.text if title_el is not None else ""
                link = link_el.text if link_el is not None else ""
                desc = desc_el.text if desc_el is not None else ""

                # Strip HTML from description
                desc = re.sub(r"<[^>]+>", " ", desc or "").strip()

                if title and (link or desc):
                    items.append({
                        "source": "rss",
                        "title": title,
                        "url": link,
                        "content": f"{title}\n\n{desc}",
                        "topic": "news",
                        "quality": "medium",
                    })

            return items
        except Exception as e:
            logger.debug(f"RSS parse error: {e}")
            return []

    async def crawl_url(self, url: str, topic: str = "") -> Optional[Dict[str, Any]]:
        """Crawl a specific URL."""
        content = await self._fetch_clean(url)
        if not content:
            return None
        return {
            "source": "direct",
            "title": url,
            "url": url,
            "content": content[:4000],
            "topic": topic or url,
            "quality": "medium",
        }

    async def _fetch_clean(self, url: str) -> str:
        """Fetch URL and extract clean readable text."""
        try:
            import httpx
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(
                timeout=12, follow_redirects=True, verify=False
            ) as client:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; NEXUS-AI/1.0; "
                        "+https://github.com/nexus-ai)"
                    )
                }
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return ""

                ct = resp.headers.get("content-type", "")
                if "text/html" not in ct and "text/plain" not in ct:
                    return ""

                soup = BeautifulSoup(resp.text, "html.parser")

                # Remove clutter
                for tag in soup(
                    ["script", "style", "nav", "footer", "header",
                     "aside", "form", "iframe", "noscript", "ads"]
                ):
                    tag.decompose()

                # Try to get main content area
                main = (
                    soup.find("main")
                    or soup.find("article")
                    or soup.find(id="content")
                    or soup.find(class_="content")
                    or soup.find(class_="post-content")
                    or soup.body
                )

                if main:
                    text = main.get_text(separator=" ", strip=True)
                else:
                    text = soup.get_text(separator=" ", strip=True)

                # Collapse whitespace
                text = re.sub(r"\s+", " ", text).strip()
                return text

        except Exception as e:
            logger.debug(f"Fetch failed {url}: {e}")
            return ""

    def _chunk_text(self, text: str, max_chars: int = 2000) -> List[str]:
        """Split long text into chunks at paragraph boundaries."""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < max_chars:
                current += "\n\n" + p
            else:
                if current:
                    chunks.append(current.strip())
                current = p
        if current:
            chunks.append(current.strip())
        return chunks or [text[:max_chars]]

    def _is_visited(self, url: str) -> bool:
        h = hashlib.md5(url.encode()).hexdigest()
        return h in self._visited

    def _mark_visited(self, url: str):
        h = hashlib.md5(url.encode()).hexdigest()
        self._visited.add(h)

    def reset_visited(self):
        self._visited.clear()


# Global singleton
crawler = NexusCrawler()
