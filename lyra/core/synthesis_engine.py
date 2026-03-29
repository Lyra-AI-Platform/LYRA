"""
Lyra AI Platform — Knowledge Synthesis Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Periodically synthesizes raw stored knowledge into higher-order insights,
principles, and cross-domain connections. Transforms fact accumulation into
genuine wisdom growth — the difference between knowing facts and understanding.

Every 4 hours:
  1. Takes clusters of related facts by topic
  2. Uses the LLM to extract principles, contradictions, and key insights
  3. Generates cross-domain connections between different knowledge areas
  4. Stores synthesized wisdom at high importance for future retrieval
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class SynthesisStatus:
    running: bool = False
    synthesis_count: int = 0
    last_synthesis: str = ""
    topics_synthesized: List[str] = field(default_factory=list)


class KnowledgeSynthesizer:
    """
    Transforms raw crawled facts into distilled wisdom.

    Raw knowledge is useful, but synthesized knowledge is powerful.
    This engine periodically:
      - Groups facts by topic
      - Extracts core principles using the LLM
      - Identifies cross-domain patterns
      - Stores high-quality synthesized entries that are preferentially
        retrieved during conversations, boosting response quality over time.
    """

    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.synthesis_interval = 14400  # 4 hours
        self.synthesis_count = 0
        self.last_synthesis = ""
        self.topics_synthesized: List[str] = []

    # ─── Control ───

    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._synthesis_loop())
        logger.info("KnowledgeSynthesizer started (4h cycle)")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None

    # ─── Main Loop ───

    async def _synthesis_loop(self):
        """Background synthesis loop — runs every 4 hours."""
        # Initial delay: let system start and accumulate some knowledge first
        await asyncio.sleep(180)
        while self.running:
            try:
                await self._run_synthesis_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Synthesis cycle error: {e}")
            await asyncio.sleep(self.synthesis_interval)

    async def _run_synthesis_cycle(self):
        """One full synthesis cycle: synthesize top topics + cross-domain."""
        from lyra.memory.vector_memory import memory
        from lyra.core.engine import engine
        from lyra.core.auto_learner import auto_learner

        if not engine.loaded_model:
            logger.debug("Synthesis skipped: no model loaded")
            return

        # Check if there's enough knowledge to synthesize
        stats = memory.get_stats()
        if stats.get("count", 0) < 10:
            logger.debug("Synthesis skipped: not enough memories yet")
            return

        logger.info("Starting knowledge synthesis cycle")

        # Get top topics from auto-learner
        top_topics = [t for t, _ in auto_learner.topic_scores.most_common(15)]
        if not top_topics:
            # Fall back to retrieving recent knowledge types
            return

        synthesized = []
        for topic in top_topics[:6]:  # Synthesize top 6 topics per cycle
            if not self.running:
                break
            try:
                success = await self._synthesize_topic(topic, memory, engine)
                if success:
                    synthesized.append(topic)
                await asyncio.sleep(5)  # Space out LLM calls
            except Exception as e:
                logger.debug(f"Topic synthesis failed for '{topic}': {e}")

        # Cross-domain synthesis if we have multiple topics
        if len(top_topics) >= 3:
            try:
                await self._cross_domain_synthesis(top_topics[:5], memory, engine)
            except Exception as e:
                logger.debug(f"Cross-domain synthesis failed: {e}")

        self.synthesis_count += 1
        self.last_synthesis = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.topics_synthesized = synthesized
        logger.info(
            f"Synthesis cycle complete: {len(synthesized)} topics synthesized"
        )

    # ─── Topic Synthesis ───

    async def _synthesize_topic(self, topic: str, memory, engine) -> bool:
        """
        Synthesize all stored knowledge about a topic into a wisdom entry.
        Returns True if synthesis was stored.
        """
        # Retrieve raw facts — multiple types
        facts = memory.retrieve(topic, n_results=12, memory_type="learned_knowledge")
        news = memory.retrieve(topic, n_results=4, memory_type="learned_news")
        existing = memory.retrieve(topic, n_results=2, memory_type="synthesized_wisdom")
        all_items = facts + news

        if len(all_items) < 3:
            return False

        # Compile source material (deduplicate by first 100 chars)
        seen_prefixes = set()
        unique_items = []
        for item in all_items:
            prefix = item["content"][:100]
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                unique_items.append(item)

        source_text = "\n\n---\n\n".join([
            item["content"][:700] for item in unique_items[:10]
        ])

        # Include any existing synthesis for continuity
        prev_synthesis = ""
        if existing:
            prev_synthesis = f"\nPreviously synthesized:\n{existing[0]['content'][:300]}\n"

        prompt = f"""You are a knowledge synthesis engine. Analyze the following source material about "{topic}" and produce a high-quality synthesis document.

{prev_synthesis}
SOURCE MATERIAL ({len(unique_items)} sources):
{source_text}

Produce a synthesis with these sections:
1. CORE INSIGHT: The single most important thing to understand about {topic} (2-3 sentences)
2. KEY PRINCIPLES: 3-4 fundamental principles or facts (bullet points)
3. IMPORTANT CONNECTIONS: How this topic connects to other fields or ideas (2-3 connections)
4. PRACTICAL SIGNIFICANCE: Why this matters in the real world (2-3 sentences)
5. OPEN QUESTIONS: What is still uncertain or debated (1-2 points)

Be precise, insightful, and go beyond restating facts. Maximum 350 words."""

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You are an expert knowledge synthesizer. Your role is to distill "
                "raw information into deep understanding and transferable principles. "
                "Focus on insight over enumeration."
            ),
            max_tokens=600,
            temperature=0.35,
            stream=True,
        ):
            parts.append(token)

        synthesis = "".join(parts).strip()
        if len(synthesis) < 150:
            return False

        content = (
            f"[SYNTHESIZED WISDOM — Topic: {topic}]\n"
            f"Synthesized from {len(unique_items)} sources on "
            f"{datetime.now().strftime('%Y-%m-%d')}:\n\n{synthesis}"
        )

        memory.store(
            content=content,
            memory_type="synthesized_wisdom",
            metadata={
                "topic": topic,
                "source_count": str(len(unique_items)),
                "synthesized_at": datetime.now().isoformat(),
                "importance": "10",
            },
        )
        logger.info(f"Synthesized wisdom stored for: {topic}")
        return True

    # ─── Cross-Domain Synthesis ───

    async def _cross_domain_synthesis(
        self, topics: List[str], memory, engine
    ):
        """
        Generate insights from unexpected connections between different topics.
        This is the highest-value synthesis — finding patterns across domains.
        """
        topics_str = ", ".join(topics[:5])

        # Retrieve the best available knowledge per topic
        wisdom_items = []
        for topic in topics[:5]:
            # Prefer synthesized wisdom; fall back to raw knowledge
            for mtype in ["synthesized_wisdom", "learned_knowledge"]:
                items = memory.retrieve(topic, n_results=1, memory_type=mtype)
                if items:
                    snippet = items[0]["content"][:350]
                    wisdom_items.append(f"[{topic.upper()}]:\n{snippet}")
                    break

        if len(wisdom_items) < 2:
            return

        combined = "\n\n".join(wisdom_items)

        prompt = f"""You are a cross-disciplinary insight generator. Below is knowledge from different domains. Your task is to find deep, non-obvious connections.

DOMAINS: {topics_str}

KNOWLEDGE:
{combined}

Generate 2-3 cross-domain insights. These should be:
- Non-obvious connections not apparent from any single domain
- Unified principles that appear across multiple fields
- Analogies that deepen understanding of each domain
- Emergent patterns only visible when looking across disciplines

Each insight should be 2-3 sentences. Be specific — name the domains and the connection clearly. Maximum 250 words."""

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You excel at finding deep patterns and analogies across disciplines. "
                "You reveal the hidden structure that connects seemingly unrelated fields."
            ),
            max_tokens=400,
            temperature=0.55,
            stream=True,
        ):
            parts.append(token)

        insight = "".join(parts).strip()
        if len(insight) < 80:
            return

        content = (
            f"[CROSS-DOMAIN INSIGHT — Topics: {topics_str}]\n"
            f"Generated on {datetime.now().strftime('%Y-%m-%d')}:\n\n{insight}"
        )
        memory.store(
            content=content,
            memory_type="synthesized_wisdom",
            metadata={
                "topic": "cross_domain",
                "topics_connected": topics_str,
                "synthesized_at": datetime.now().isoformat(),
                "importance": "9",
            },
        )
        logger.info(f"Cross-domain insight stored for: {topics_str}")

    # ─── Manual Trigger ───

    async def synthesize_now(self, topic: str = "") -> Dict[str, Any]:
        """Manually trigger synthesis for a specific topic or all top topics."""
        from lyra.memory.vector_memory import memory
        from lyra.core.engine import engine

        if not engine.loaded_model:
            return {"success": False, "error": "No model loaded"}

        if topic:
            success = await self._synthesize_topic(topic, memory, engine)
            return {"success": success, "topic": topic}
        else:
            await self._run_synthesis_cycle()
            return {"success": True, "synthesis_count": self.synthesis_count}

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "synthesis_count": self.synthesis_count,
            "last_synthesis": self.last_synthesis,
            "topics_synthesized": self.topics_synthesized,
            "interval_hours": self.synthesis_interval / 3600,
        }


# Global singleton
synthesizer = KnowledgeSynthesizer()
