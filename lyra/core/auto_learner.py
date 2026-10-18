"""
Lyra AI Platform — Autonomous Learning Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Lyra teaches itself by:
  1. Extracting topics from conversations using LLM intelligence (not just regex)
  2. Detecting knowledge gaps — things the AI was uncertain about
  3. Generating targeted learning questions for precise knowledge acquisition
  4. Periodically crawling the web on those topics autonomously
  5. Exponentially expanding: each learned topic spawns 3-5 follow-up questions
  6. Storing all learned knowledge in vector memory + knowledge graph
  7. Reading RSS feeds for fresh daily knowledge

The key to exponential learning: the LLM itself directs its own learning,
identifying what it doesn't know and generating precise questions to fill gaps.
Each crawl cycle compounds on the previous one.
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
    """
    Regex-based topic extractor — used as fallback when no model is loaded.
    Fast but limited: catches explicit topics, misses implicit interests and gaps.
    """

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
        """Extract candidate topics from text using regex patterns."""
        text_lower = text.lower()
        topics = []

        # 1. Quoted terms (highest confidence)
        quoted = re.findall(r'"([^"]{3,50})"', text)
        topics.extend(quoted)

        # 2. Capitalized multi-word phrases (proper nouns, named concepts)
        proper = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text)
        topics.extend(proper)

        # 3. Single capitalized words (proper nouns)
        single_proper = re.findall(r'\b([A-Z][a-z]{3,})\b', text)
        topics.extend(single_proper)

        # 4. Technical terms (camelCase, hyphenated, with numbers)
        tech = re.findall(
            r'\b([a-z]+(?:[A-Z][a-z]+)+|[a-z]+-[a-z]+|[a-z]+\d+[a-z]*)\b', text
        )
        topics.extend(tech)

        # 5. "tell me about X", "what is X", "explain X" patterns
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

        return result[:10]


class LLMTopicExtractor:
    """
    LLM-powered topic and knowledge-gap extractor.

    Dramatically superior to regex extraction:
    - Understands implicit interests (not just explicitly mentioned topics)
    - Detects knowledge gaps in AI responses ("I'm not sure about X")
    - Generates specific learning questions ("What are the types of X?")
    - Produces expansion topics for rabbit-hole exploration

    Falls back to regex TopicExtractor if model is not loaded.
    """

    def __init__(self):
        self._regex_fallback = TopicExtractor()

    async def extract_from_exchange(
        self,
        user_message: str,
        assistant_response: str = "",
    ) -> Dict[str, List[str]]:
        """
        Extract learning signals from a conversation exchange.

        Returns a dict with:
          explicit_topics   — directly mentioned subjects
          implicit_topics   — inferred interests from context
          knowledge_gaps    — things the AI was uncertain about
          learning_questions — specific questions to research
        """
        from lyra.core.engine import engine

        # Use LLM extraction if model is loaded
        if engine.loaded_model:
            try:
                return await self._llm_extract(user_message, assistant_response, engine)
            except Exception as e:
                logger.debug(f"LLM extraction failed, using regex: {e}")

        # Fallback: regex on both messages
        topics = self._regex_fallback.extract(user_message)
        if assistant_response:
            topics += self._regex_fallback.extract(assistant_response)[:3]
        return {
            "explicit_topics": list(set(topics)),
            "implicit_topics": [],
            "knowledge_gaps": [],
            "learning_questions": [],
        }

    async def _llm_extract(
        self, user_msg: str, assistant_msg: str, engine
    ) -> Dict[str, List[str]]:
        """Extract topics and gaps using the LLM."""
        # Truncate inputs
        u = user_msg[:600]
        a = assistant_msg[:600] if assistant_msg else "(no response)"

        prompt = f"""Analyze this conversation exchange and extract learning signals for an AI knowledge system.

USER: {u}

ASSISTANT: {a}

Extract the following (be specific, use 2-5 word phrases, max 5 per category):

1. explicit_topics: Subjects directly mentioned or discussed
2. implicit_topics: What the user is likely interested in learning more about (inferred)
3. knowledge_gaps: Topics the AI was uncertain about, hedged on, or didn't fully cover
4. learning_questions: Specific questions to research (e.g. "What are the mechanisms of X?")

Output ONLY valid JSON:
{{"explicit_topics": [...], "implicit_topics": [...], "knowledge_gaps": [...], "learning_questions": [...]}}"""

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You extract learning topics from conversations. "
                "Output ONLY valid JSON. No extra text."
            ),
            max_tokens=300,
            temperature=0.2,
            stream=True,
        ):
            parts.append(token)

        raw = "".join(parts).strip()

        try:
            import json as _json
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = _json.loads(raw[start:end])
                # Normalize to string lists
                result = {}
                for key in ["explicit_topics", "implicit_topics", "knowledge_gaps", "learning_questions"]:
                    val = data.get(key, [])
                    result[key] = [str(v).strip()[:80] for v in val if str(v).strip()][:5]
                return result
        except Exception:
            pass

        # Parse failure — fall back
        topics = self._regex_fallback.extract(user_msg)
        return {
            "explicit_topics": topics,
            "implicit_topics": [],
            "knowledge_gaps": [],
            "learning_questions": [],
        }

    async def generate_expansion_questions(
        self, topic: str, learned_content: str, engine
    ) -> List[str]:
        """
        After learning about a topic, generate 3-5 follow-up questions
        to explore deeper. This is the mechanism for exponential expansion.
        """
        try:
            prompt = (
                f"You just learned about '{topic}'. Based on this knowledge:\n\n"
                f"{learned_content[:500]}\n\n"
                f"Generate 3-4 specific follow-up questions to explore this topic deeper. "
                f"Each question should target a distinct sub-aspect.\n"
                f"Output ONLY a numbered list of questions, nothing else."
            )

            parts = []
            async for token in engine.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You generate specific research questions. Output only a numbered list.",
                max_tokens=200,
                temperature=0.4,
                stream=True,
            ):
                parts.append(token)

            raw = "".join(parts).strip()
            questions = []
            for line in raw.split("\n"):
                line = line.strip().lstrip("0123456789.-) ")
                if len(line) > 10 and "?" in line or len(line) > 20:
                    questions.append(line[:100])

            return questions[:4]
        except Exception as e:
            logger.debug(f"Expansion question generation failed: {e}")
            return []


class AutoLearner:
    """
    Lyra's autonomous background learning engine.

    Runs continuously, learning from conversations and the web.
    Uses LLM intelligence to direct its own learning — not just regex.

    The exponential growth mechanism:
      1. LLM detects explicit topics, implicit interests, AND knowledge gaps
      2. Knowledge gaps get highest learning priority
      3. Each crawled topic generates 3-5 expansion questions
      4. Expansion questions become new learning targets
      5. Synthesizer periodically distills raw facts into wisdom
      6. Wisdom is injected back into future conversations
    """

    def __init__(self):
        self.enabled = True
        self.running = False
        self._task: Optional[asyncio.Task] = None

        # Extractors
        self.llm_extractor = LLMTopicExtractor()
        self._regex_extractor = TopicExtractor()  # legacy fallback

        # Topic tracking — scored by priority
        # knowledge_gaps=5, user_explicit=2, implicit=1.5, ai_response=1, expansion=0.8
        self.topic_scores: Counter = Counter()
        self.topic_last_crawled: Dict[str, float] = {}
        self.learned_count: int = 0
        self.crawl_count: int = 0
        self.last_crawl_time: Optional[str] = None
        self.current_activity: str = "idle"
        self.activity_log: List[Dict] = []

        # Async extraction queue — processes LLM extractions without blocking chat
        self._extraction_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._extraction_task: Optional[asyncio.Task] = None

        # Config — tuned for faster, broader learning
        self.crawl_interval_seconds = 600    # crawl every 10 min (was 30)
        self.max_topics_per_cycle = 8        # 8 topics per cycle (was 3)
        self.min_topic_score = 1.5           # lower threshold for gaps/questions
        self.rss_interval_seconds = 3600     # RSS every 60 min
        self._last_rss_crawl = 0.0

        self._load_state()

    # ─── Public Control ───

    def start(self):
        """Start the autonomous learning background tasks."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._learning_loop())
        self._extraction_task = asyncio.create_task(self._extraction_loop())
        logger.info("AutoLearner started (LLM-guided, 10-min cycles)")

    def stop(self):
        """Stop the learning background tasks."""
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._extraction_task:
            self._extraction_task.cancel()
            self._extraction_task = None
        logger.info("AutoLearner stopped")

    def observe_message(self, role: str, content: str):
        """
        Feed a conversation message to the learner.
        Queues async LLM extraction (non-blocking).
        Falls back to synchronous regex for immediate basic scoring.
        """
        if not content or role == "system":
            return

        # Immediate scoring via regex (fast, non-blocking)
        topics = self._regex_extractor.extract(content)
        score = 2.0 if role == "user" else 1.0
        for topic in topics:
            self.topic_scores[topic.lower()] += score

        # Queue async LLM extraction for deeper analysis
        if role == "user":
            try:
                self._extraction_queue.put_nowait({"role": role, "content": content})
            except asyncio.QueueFull:
                pass

        if topics:
            self._save_state()

    def observe_exchange(self, user_msg: str, assistant_msg: str):
        """
        Feed a complete exchange (user + assistant) for LLM-powered extraction.
        Call this after assistant responds to capture knowledge gaps.
        """
        try:
            self._extraction_queue.put_nowait({
                "role": "exchange",
                "user": user_msg,
                "assistant": assistant_msg,
            })
        except asyncio.QueueFull:
            pass

    def add_topic(self, topic: str, priority: int = 5):
        """Manually add a topic to learn about."""
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
            "activity_log": self.activity_log[-20:],
            "topic_count": len(self.topic_scores),
        }

    # ─── Async Extraction Loop ───

    async def _extraction_loop(self):
        """
        Background loop that processes queued messages through LLM extraction.
        Runs independently so chat is never blocked.
        """
        while self.running:
            try:
                item = await asyncio.wait_for(
                    self._extraction_queue.get(), timeout=5.0
                )
                await self._process_extraction(item)
                await asyncio.sleep(1)  # Rate limit LLM calls
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Extraction loop error: {e}")

    async def _process_extraction(self, item: Dict):
        """Process one queued extraction using LLM."""
        try:
            if item["role"] == "exchange":
                signals = await self.llm_extractor.extract_from_exchange(
                    item["user"], item["assistant"]
                )
            else:
                signals = await self.llm_extractor.extract_from_exchange(
                    item["content"]
                )

            # Score topics by category importance
            for topic in signals.get("explicit_topics", []):
                self.topic_scores[topic.lower()] += 2.0

            for topic in signals.get("implicit_topics", []):
                self.topic_scores[topic.lower()] += 1.5

            for gap in signals.get("knowledge_gaps", []):
                # Knowledge gaps get highest priority — fill actual holes!
                self.topic_scores[gap.lower()] += 5.0
                self._log_activity(f"🔍 Knowledge gap detected: {gap}")

            for question in signals.get("learning_questions", []):
                # Learning questions stored as-is (they're already queryable)
                self.topic_scores[question.lower()] += 3.0

            self._save_state()

        except Exception as e:
            logger.debug(f"Extraction processing failed: {e}")

    # ─── Background Learning Loop ───

    async def _learning_loop(self):
        """Main autonomous learning loop."""
        logger.info("AutoLearner loop running")
        await asyncio.sleep(30)  # Initial delay

        while self.running:
            try:
                await self._learning_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Learning cycle error: {e}")

            await asyncio.sleep(self.crawl_interval_seconds)

    async def _learning_cycle(self):
        """One full learning cycle: pick topics, crawl, store, expand."""
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

        self._log_activity(f"📚 Learning about: {', '.join(topics_to_crawl[:4])}...")

        # 3. Crawl each topic
        total_learned = 0
        all_learned_content = []

        for topic in topics_to_crawl:
            if not self.running:
                break
            learned, content_sample = await self._crawl_and_store(topic, crawler, memory)
            total_learned += learned
            if content_sample:
                all_learned_content.append((topic, content_sample))
            self.topic_last_crawled[topic.lower()] = time.time()
            await asyncio.sleep(5)  # Respectful crawl delay

        self.crawl_count += 1
        self.last_crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.current_activity = f"idle — last learned {total_learned} facts"
        self._log_activity(f"✅ Cycle done: {total_learned} facts stored")
        self._save_state()

        # 4. Exponential expansion: generate follow-up questions from learned content
        await self._generate_expansion_topics(all_learned_content)

        # 5. Discover related topics (original regex-based discovery, still useful)
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
                if len(content) > 500:
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
    ):
        """
        Crawl a topic and store results.
        Returns (count_stored, sample_content) for expansion generation.
        """
        self.current_activity = f"🌐 Learning about: {topic[:50]}"
        logger.info(f"AutoLearner crawling: {topic}")

        sample_content = ""

        try:
            from lyra.memory.graph_memory import graph_memory

            results = await crawler.crawl_topic(topic, depth=1)
            stored = 0

            for item in results:
                content = item.get("content", "")
                if not content or len(content) < 500:
                    continue

                # Capture a sample for expansion generation
                if not sample_content and len(content) > 200:
                    sample_content = content[:800]

                # Store in knowledge graph
                graph_memory.store_knowledge(
                    topic=topic, content=content, source_url=item.get("url", ""),
                )
                if item.get("source") == "wikipedia":
                    graph_memory.store_wikipedia_article(
                        title=item.get("title", topic), content=content,
                        url=item.get("url", ""), topic=topic,
                        related_topics=item.get("related_topics", []),
                    )

                # Store main chunk in vector memory
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

                # Store additional Wikipedia chunks
                for extra_chunk in item.get("full_chunks", [])[1:4]:
                    if len(extra_chunk) > 500:
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

            self._log_activity(f"🧠 Learned {stored} facts about '{topic[:40]}'")
            return stored, sample_content

        except Exception as e:
            logger.error(f"Crawl failed for '{topic}': {e}")
            return 0, ""

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
        """Select which topics to crawl this cycle, prioritizing gaps and questions."""
        candidates = []

        for topic, score in self.topic_scores.most_common(100):
            if score < self.min_topic_score:
                break

            # Cooldown: avoid re-crawling too recently
            last = self.topic_last_crawled.get(topic.lower(), 0)
            # Knowledge gaps get shorter cooldown (3h), general topics 6h
            is_gap = score >= 5.0  # likely a knowledge gap
            cooldown = 3 * 3600 if is_gap else 6 * 3600
            if time.time() - last < cooldown:
                continue

            candidates.append(topic)
            if len(candidates) >= self.max_topics_per_cycle:
                break

        return candidates

    # ─── Exponential Expansion ───

    async def _generate_expansion_topics(
        self, learned_items: List[tuple]
    ):
        """
        Generate follow-up learning questions from what was just learned.
        This is the exponential mechanism: each topic spawns 3-4 new questions.
        """
        from lyra.core.engine import engine

        if not engine.loaded_model or not learned_items:
            return

        self._log_activity("🚀 Generating expansion questions...")
        expansion_count = 0

        for topic, content in learned_items[:3]:  # Expand top 3 crawled topics
            try:
                questions = await self.llm_extractor.generate_expansion_questions(
                    topic, content, engine
                )
                for question in questions:
                    q_lower = question.lower()
                    # Add with moderate priority (below user/gap, above random)
                    if q_lower not in self.topic_scores or self.topic_scores[q_lower] < 1:
                        self.topic_scores[q_lower] += 1.2
                        expansion_count += 1
                await asyncio.sleep(2)  # Rate limit
            except Exception as e:
                logger.debug(f"Expansion generation failed for '{topic}': {e}")

        if expansion_count > 0:
            self._log_activity(f"🚀 Added {expansion_count} expansion questions to queue")
            self._save_state()

    async def _discover_related_topics(self):
        """
        Discover related topics from recently learned content.
        Original regex-based discovery — still useful as a fast complement.
        """
        try:
            from lyra.memory.vector_memory import memory
            recent = memory.retrieve(
                "recent learning knowledge", n_results=5, memory_type="learned_knowledge"
            )
            for item in recent:
                content = item.get("content", "")
                if content:
                    new_topics = self._regex_extractor.extract(content)
                    for t in new_topics[:3]:
                        tl = t.lower()
                        if tl not in self.topic_scores or self.topic_scores[tl] < 3:
                            self.topic_scores[tl] += 0.8  # Low priority discovery
        except Exception as e:
            logger.debug(f"Topic discovery failed: {e}")

    # ─── Activity Logging ───

    def _log_activity(self, message: str):
        self.activity_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": message,
        })
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
