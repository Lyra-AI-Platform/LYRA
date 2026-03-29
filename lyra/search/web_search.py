"""Lyra Web Search"""
import logging
logger = logging.getLogger(__name__)
class WebSearch:
    async def search(self, query: str, max_results: int = 5):
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                return [{"title": r.get("title",""), "url": r.get("href",""), "snippet": r.get("body","")} for r in ddgs.text(query, max_results=max_results)]
        except Exception as e:
            logger.debug(f"Search error: {e}"); return []
search = WebSearch()
