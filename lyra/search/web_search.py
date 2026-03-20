"""
NEXUS Web Search
Searches the web and returns formatted results.
Uses DuckDuckGo (no API key required) + optional SerpAPI.
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class WebSearch:
    """Web search plugin for NEXUS."""

    async def search(
        self,
        query: str,
        max_results: int = 5,
        fetch_content: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search the web for a query.
        Returns list of {title, url, snippet, content} dicts.
        """
        results = await self._ddg_search(query, max_results)
        if fetch_content and results:
            results = await self._fetch_pages(results)
        return results

    async def _ddg_search(self, query: str, max_results: int) -> List[Dict]:
        """Search using DuckDuckGo (no API key needed)."""
        try:
            from duckduckgo_search import DDGS
            loop = asyncio.get_event_loop()

            def _run():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))

            raw = await loop.run_in_executor(None, _run)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "content": "",
                }
                for r in raw
            ]
        except ImportError:
            logger.warning("duckduckgo-search not installed. Run: pip install duckduckgo-search")
            return []
        except Exception as e:
            logger.error(f"DDG search error: {e}")
            return []

    async def _fetch_pages(self, results: List[Dict]) -> List[Dict]:
        """Fetch and extract text content from result pages."""
        tasks = [self._fetch_page(r) for r in results]
        fetched = await asyncio.gather(*tasks, return_exceptions=True)
        for i, content in enumerate(fetched):
            if isinstance(content, str):
                results[i]["content"] = content[:3000]  # limit per page
        return results

    async def _fetch_page(self, result: Dict) -> str:
        """Fetch a single page and extract readable text."""
        url = result.get("url", "")
        if not url:
            return ""
        try:
            import httpx
            from bs4 import BeautifulSoup
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Remove scripts, styles
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    text = soup.get_text(separator=" ", strip=True)
                    # Collapse whitespace
                    import re
                    text = re.sub(r"\s+", " ", text).strip()
                    return text[:3000]
        except Exception:
            return result.get("snippet", "")
        return ""

    def format_for_prompt(self, results: List[Dict]) -> str:
        """Format search results as context for the AI."""
        if not results:
            return "No search results found."

        lines = ["[WEB SEARCH RESULTS]"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n[{i}] {r['title']}")
            lines.append(f"URL: {r['url']}")
            if r.get("content"):
                lines.append(f"Content: {r['content'][:500]}...")
            elif r.get("snippet"):
                lines.append(f"Snippet: {r['snippet']}")
        lines.append("\n[Use these results to answer accurately. Always cite URLs.]")
        return "\n".join(lines)


# Global singleton
search = WebSearch()
