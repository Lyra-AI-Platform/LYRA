"""
Lyra AI Platform — Autonomous Learning Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Lyra teaches itself by:
  1. Extracting topics from conversations (what is the user interested in?)
  2. Periodically crawling the web on those topics autonomously
  3. Storing all learned knowledge in the vector memory
  4. Discovering related topics and recursively learning more
  5. Reading RSS feeds for fresh daily knowledge
  6. Prioritizing topics by frequency and recency

This runs as a background asyncio task — Lyra learns while you chat or idle.
"""
import asyncio
import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)

LEARNING_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "memory" / "learning_state.json"
LEARNING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


class TopicExtractor:
    """Extracts interesting topics from conversation text."""

    # Topics Lyra will never bother crawling (too generic / unhelpful)
    IGNORE_WORDS: Set[str] = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "can", "could", "should", "may", "might", "shall", "must",
        "hi", "hello", "hey", "thanks", "thank", "you", "me", "my",
        "i", "we", "they", "it", "this", "that", "what", "how",
        "why", "where", "when", "who", "which", "please", "help",
        "tell", "explain", "write", "create", "make", "build", "show",
        "nexus", "ai", "model", "chat", "message", "response",
    }

    def extract(self, text: str) -> List[str]:
        """Extract candidate topics from text."""
        text_lower = text.lower()
        topics = []

        # 1. Extract quoted terms (highest confidence)
        quoted = re.findall(r'"([^"]{3,50})"', text)
        topics.extend(quoted)

        # 2. Extract capitalized multi-word phrases (proper nouns, concepts)
        proper = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text)
        topics.extend(proper)

        # 3. Extract single capitalized words (proper nouns)
        single_proper = re.findall(r'\b([A-Z][a-z]{3,})\b', text)
        topics.extend(single_proper)

        # 4. Extract technical terms (camelCase, hyphenated, with numbers)
        tech = re.findall(r'\b([a-z]+(?:[A-Z][a-z]+)+|[a-z]+-[a-z]+|[a-z]+\d+[a-z]*)\b', text)
        topics.extend(tech)

        # 5. Detect "tell me about X", "what is X", "explain X" patterns
        about_patterns = [
            r'(?:about|regarding|on|explain|what is|what are|tell me about|learn about)\s+([a-zA-Z][a-zA-Z\s]{3,40}?)(?:[.?!,]|$)',
            r'(?:how does|how do)\s+([a-zA-Z][a-zA-Z\s]{3,40}?)(?:\s+work|\s+function)',
        ]
        for pattern in about_patterns:
            matches = re.findall(pattern, text_lower)
            topics.extend(m.strip() for m in matches)

        # Filter and clean
        cleaned = []
        for t in topics:
            t = t.strip()
            words = t.lower().split()
            if (
                2 <= len(t) <= 60
                and not all(w in self.IGNORE_WORDS for w in words)
                and len(words) <= 5
            ):
                cleaned.append(t)

        # Deduplicate preserving order
        seen = set()
        result = []
        for t in cleaned:
            tl = t.lower()
            if tl not in seen:
                seen.add(tl)
                result.append(t)

        return result[:10]  # max 10 per message


class AutoLearner:
    """
    Lyra's autonomous background learning engine.
    Runs continuously, learning from conversations and the web.
    """

    def __init__(self):
        self.enabled = True
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.extractor = TopicExtractor()

        # Topic interest tracking
        self.topic_scores: Counter = Counter()         # topic -> interest score
        self.topic_last_crawled: Dict[str, float] = {} # topic -> timestamp
        self.learned_count: int = 0
        self.crawl_count: int = 0
        self.last_crawl_time: Optional[str] = None
        self.current_activity: str = "idle"
        self.activity_log: List[Dict] = []            # recent activity

        # Config
        self.crawl_interval_seconds = 1800   # crawl every 30 min
        self.max_topics_per_cycle = 3        # max topics to crawl per cycle
        self.min_topic_score = 2             # min score before crawling
        self.rss_interval_seconds = 3600    # RSS every 60 min
        self._last_rss_crawl = 0.0

        self._load_state()

    # ─── Public Control ───

    def start(self):
        """Start the autonomous learning background task."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._learning_loop())
        logger.info("AutoLearner started")

    def stop(self):
        """Stop the learning background task."""
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("AutoLearner stopped")

    def observe_message(self, role: str, content: str):
        """
        Feed a conversation message to the learner.
        Lyra extracts topics it should learn about.
        """
        if not content or role == "system":
            return

        topics = self.extractor.extract(content)
        for topic in topics:
            # User messages get 2 points, assistant messages get 1
            score = 2 if role == "user" else 1
            self.topic_scores[topic.lower()] += score

        if topics:
            logger.debug(f"Observed topics from {role}: {topics}")
            self._save_state()

    def add_topic(self, topic: str, priority: int = 5):
        """Manually add a topic to learn about (e.g. from settings)."""
        self.topic_scores[topic.lower()] += priority
        self._save_state()
        logger.info(f"Manual topic added: {topic} (priority={priority})")

    def get_status(self) -> Dict[str, Any]:
        """Return current learning status for the UI."""
        top_topics = [
            {"topic": t, "score": s, "crawled": t in self.topic_last_crawled}
            for t, s in self.topic_scores.most_common(20)
        ]
        return {
            "enabled": self.enabled,
            "running": self.running,
            "learned_count": self.learned_count,
            "crawl_count": self.crawl_count,
            "last_crawl": self.last_crawl_time,
            "current_activity": self.current_activity,
            "top_topics": top_topics,
            "activity_log": self.activity_log[-20:],  # last 20 events
            "topic_count": len(self.topic_scores),
        }

    # ─── Background Loop ───

    async def _learning_loop(self):
        """Main autonomous learning loop."""
        logger.info("AutoLearner loop running")
        # Initial delay so server starts cleanly first
        await asyncio.sleep(30)

        while self.running:
            try:
                await self._learning_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Learning cycle error: {e}")

            # Wait before next cycle
            await asyncio.sleep(self.crawl_interval_seconds)

    async def _learning_cycle(self):
        """One full learning cycle: pick topics, crawl, store."""
        from lyra.search.crawler import crawler
        from lyra.memory.vector_memory import memory

        self.current_activity = "analyzing topics..."
        self._log_activity("🔍 Starting learning cycle")

        # 1. RSS feeds (periodically)
        now = time.time()
        if now - self._last_rss_crawl > self.rss_interval_seconds:
            await self._crawl_rss(crawler, memory)
            self._last_rss_crawl = now

        # 2. Pick best topics to crawl
        topics_to_crawl = self._pick_topics()

        if not topics_to_crawl:
            self.current_activity = "idle — waiting for topics"
            self._log_activity("💤 No topics ready to crawl yet")
            return

        self._log_activity(f"📚 Will learn about: {', '.join(topics_to_crawl)}")

        # 3. Crawl each topic
        total_learned = 0
        for topic in topics_to_crawl:
            if not self.running:
                break
            learned = await self._crawl_and_store(topic, crawler, memory)
            total_learned += learned
            self.topic_last_crawled[topic.lower()] = time.time()
            await asyncio.sleep(5)  # respectful crawl delay

        self.crawl_count += 1
        self.last_crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.current_activity = f"idle — last learned {total_learned} facts"
        self._log_activity(f"✅ Cycle done: {total_learned} facts stored")
        self._save_state()

        # 4. Discover related topics from what we learned
        await self._discover_related_topics()

    async def _crawl_rss(self, crawler, memory):
        """Crawl RSS feeds for fresh news."""
        self.current_activity = "📰 Reading news feeds..."
        self._log_activity("📰 Crawling RSS feeds for fresh knowledge")

        try:
            items = await crawler.crawl_rss_feeds()
            count = 0
            for item in items:
                content = item.get("content", "")
                if len(content) > 100:
                    stored = memory.store(
                        content=f"[NEWS] {item['title']}\nSource: {item['url']}\n\n{content}",
                        memory_type="learned_news",
                        metadata={
                            "source": item.get("url", "rss"),
                            "title": item.get("title", ""),
                            "quality": "medium",
                        },
                    )
                    if stored:
                        count += 1
                        self.learned_count += 1

            self._log_activity(f"📰 Stored {count} news items from RSS")
        except Exception as e:
            logger.error(f"RSS crawl failed: {e}")

    async def _crawl_and_store(
        self, topic: str, crawler, memory
    ) -> int:
        """Crawl a topic and store results. Returns count of stored chunks."""
        self.current_activity = f"🌐 Learning about: {topic}"
        logger.info(f"AutoLearner crawling: {topic}")

        try:
            results = await crawler.crawl_topic(topic, depth=1)
            stored = 0

            for item in results:
                content = item.get("content", "")
                if not content or len(content) < 100:
                    continue

                # Store main chunk
                success = memory.store(
                    content=self._format_knowledge(item, topic),
                    memory_type="learned_knowledge",
                    metadata={
                        "topic": topic,
                        "source": item.get("url", "web"),
                        "source_type": item.get("source", "web"),
                        "title": item.get("title", ""),
                        "quality": item.get("quality", "medium"),
                        "learned_at": datetime.now().isoformat(),
                    },
                )
                if success:
                    stored += 1
                    self.learned_count += 1

                # Also store additional Wikipedia chunks if present
                for extra_chunk in item.get("full_chunks", [])[1:4]:
                    if len(extra_chunk) > 100:
                        memory.store(
                            content=self._format_knowledge(
                                {**item, "content": extra_chunk}, topic
                            ),
                            memory_type="learned_knowledge",
                            metadata={
                                "topic": topic,
                                "source": item.get("url", "web"),
                                "source_type": "wikipedia_section",
                                "quality": "high",
                                "learned_at": datetime.now().isoformat(),
                            },
                        )
                        stored += 1
                        self.learned_count += 1

            self._log_activity(f"🧠 Learned {stored} facts about '{topic}'")
            return stored

        except Exception as e:
            logger.error(f"Crawl failed for '{topic}': {e}")
            return 0

    def _format_knowledge(self, item: Dict, topic: str) -> str:
        """Format a crawled item as a clean knowledge entry."""
        source = item.get("source", "web")
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("content", "")

        lines = [f"[LEARNED KNOWLEDGE — Topic: {topic}]"]
        if title:
            lines.append(f"Title: {title}")
        if url:
            lines.append(f"Source: {url} ({source})")
        lines.append(f"\n{content}")
        return "\n".join(lines)

    def _pick_topics(self) -> List[str]:
        """Select which topics to crawl this cycle."""
        candidates = []

        for topic, score in self.topic_scores.most_common(50):
            if score < self.min_topic_score:
                break

            # Don't re-crawl too recently (cooldown: 6 hours)
            last = self.topic_last_crawled.get(topic, 0)
            cooldown = 6 * 3600
            if time.time() - last < cooldown:
                continue

            candidates.append(topic)
            if len(candidates) >= self.max_topics_per_cycle:
                break

        return candidates

    async def _discover_related_topics(self):
        """
        After crawling, look at what we learned and discover
        related topics to add to the learning queue.
        """
        try:
            from lyra.memory.vector_memory import memory
            # Get recent learnings and extract new topics from them
            recent = memory.retrieve("recent learning knowledge", n_results=5, memory_type="learned_knowledge")
            for item in recent:
                content = item.get("content", "")
                if content:
                    new_topics = self.extractor.extract(content)
                    for t in new_topics[:3]:  # limit discovery rate
                        tl = t.lower()
                        if tl not in self.topic_scores or self.topic_scores[tl] < 3:
                            self.topic_scores[tl] += 1  # low priority discovery
        except Exception as e:
            logger.debug(f"Topic discovery failed: {e}")

    # ─── Activity Logging ───

    def _log_activity(self, message: str):
        self.activity_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": message,
        })
        # Keep only last 50 entries
        if len(self.activity_log) > 50:
            self.activity_log = self.activity_log[-50:]
        logger.info(f"[AutoLearner] {message}")

    # ─── State Persistence ───

    def _save_state(self):
        """Persist learning state to disk."""
        try:
            state = {
                "topic_scores": dict(self.topic_scores.most_common(500)),
                "topic_last_crawled": self.topic_last_crawled,
                "learned_count": self.learned_count,
                "crawl_count": self.crawl_count,
                "last_crawl_time": self.last_crawl_time,
                "saved_at": datetime.now().isoformat(),
            }
            LEARNING_STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"State save failed: {e}")

    def _load_state(self):
        """Load persisted learning state from disk."""
        try:
            if LEARNING_STATE_FILE.exists():
                state = json.loads(LEARNING_STATE_FILE.read_text())
                self.topic_scores = Counter(state.get("topic_scores", {}))
                self.topic_last_crawled = state.get("topic_last_crawled", {})
                self.learned_count = state.get("learned_count", 0)
                self.crawl_count = state.get("crawl_count", 0)
                self.last_crawl_time = state.get("last_crawl_time")
                logger.info(
                    f"AutoLearner state loaded: "
                    f"{len(self.topic_scores)} topics, "
                    f"{self.learned_count} facts learned"
                )
        except Exception as e:
            logger.debug(f"State load failed: {e}")


# Global singleton
auto_learner = AutoLearner()
