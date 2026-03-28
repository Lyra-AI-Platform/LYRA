"""
Lyra AI Platform — Autonomous Cognition Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Fully autonomous self-directed cognition loop.
No human input required. Runs continuously — as fast as the model allows.

The loop:
  1. Generate questions from current knowledge state (10 question strategies)
  2. Research each question against memory + knowledge graph
  3. Answer the question using the model
  4. Store the answer as synthesized knowledge
  5. Extract 3-5 new questions from each answer
  6. Immediately loop — no sleep, no waiting, no human needed

The question strategies span:
  GAPS       — What don't I know about topics I know?
  DEPTH      — How does X work at a fundamental level?
  CONNECTIONS — How does A relate to B?
  MECHANISMS — Step-by-step: exactly how does X happen?
  CRITIQUES  — What are the flaws or limits of X?
  FRONTIERS  — What is unsolved or unknown about X?
  APPLICATIONS — Real-world impact: where does X matter?
  COMPARISONS — Key differences between X and Y?
  HISTORY    — How did X develop over time?
  PREDICTIONS — Where is X heading?

This creates a self-sustaining intelligence that compounds continuously.
Every answer becomes the seed of new questions.
Every question answered deepens the knowledge graph.
No ceiling — only velocity limited by hardware.
"""
import asyncio
import json
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Deque

logger = logging.getLogger(__name__)

COGNITION_STATE_FILE = (
    Path(__file__).parent.parent.parent / "data" / "memory" / "cognition_state.json"
)
COGNITION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class CognitionEntry:
    """A single question → answer cycle."""
    question: str
    answer: str
    strategy: str
    timestamp: str
    tokens: int = 0


# 10 question generation strategies with their prompt templates
QUESTION_STRATEGIES = {
    "gaps": (
        "Based on this topic: '{topic}'\n"
        "What are 5 specific things about this topic that are unclear, "
        "uncertain, or worth investigating further? "
        "Output only a numbered list of questions."
    ),
    "depth": (
        "Topic: '{topic}'\n"
        "Generate 4 deep 'how exactly' questions — questions that force "
        "step-by-step mechanistic explanations. "
        "Output only a numbered list."
    ),
    "connections": (
        "Topics: '{topic}' and '{topic2}'\n"
        "Generate 4 questions about non-obvious connections, analogies, "
        "or shared principles between these two topics. "
        "Output only a numbered list."
    ),
    "critiques": (
        "Topic: '{topic}'\n"
        "Generate 4 critical questions: What are the weaknesses, "
        "limitations, counterarguments, or common misconceptions about this? "
        "Output only a numbered list."
    ),
    "frontiers": (
        "Topic: '{topic}'\n"
        "Generate 4 frontier questions: What remains unsolved, unknown, "
        "actively debated, or on the cutting edge of this topic? "
        "Output only a numbered list."
    ),
    "applications": (
        "Topic: '{topic}'\n"
        "Generate 4 application questions: Where and how does this matter "
        "in the real world? What problems does it solve? Who uses it? "
        "Output only a numbered list."
    ),
    "history": (
        "Topic: '{topic}'\n"
        "Generate 4 historical questions: How did this develop? "
        "What were the key breakthroughs? What did people think before? "
        "Output only a numbered list."
    ),
    "predictions": (
        "Topic: '{topic}'\n"
        "Generate 4 forward-looking questions: Where is this heading? "
        "What might change in 10 years? What emerging trends affect this? "
        "Output only a numbered list."
    ),
    "fundamentals": (
        "Topic: '{topic}'\n"
        "Generate 4 foundational questions: What are the core first principles? "
        "What assumptions underlie this? What would need to be true for this to work? "
        "Output only a numbered list."
    ),
    "synthesis": (
        "Topics known: {topics}\n"
        "Generate 4 synthesis questions that combine multiple topics into "
        "a unified understanding. Look for emergent patterns across domains. "
        "Output only a numbered list."
    ),
}

# System prompt for answering self-generated questions
ANSWER_SYSTEM_PROMPT = """You are an autonomous intelligence exploring your own knowledge.
Answer the question thoroughly and insightfully.

Requirements:
- Give a complete, substantive answer (aim for 150-300 words)
- Go beyond surface-level facts — explain mechanisms, implications, connections
- Note what you're confident about vs uncertain about
- End with: "FOLLOW-UP: [one specific question this answer raises]"

Be genuinely curious and intellectually rigorous."""


class AutonomousCognitionEngine:
    """
    Fully self-directed reasoning loop.

    Once started, continuously:
      1. Picks a question strategy
      2. Selects relevant topics from its knowledge base
      3. Generates 4-5 questions
      4. Answers each question using memory + model
      5. Stores answer as learned knowledge
      6. Extracts new questions from the answer
      7. Immediately repeats — no sleep, no human input

    The question queue grows faster than it can be answered,
    creating an ever-expanding frontier of knowledge.
    """

    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None

        # Question queue: deque of (priority, question, strategy) tuples
        # Higher priority = answered first
        self.question_queue: Deque[Dict] = deque(maxlen=500)

        # Stats
        self.questions_generated: int = 0
        self.questions_answered: int = 0
        self.cycles_completed: int = 0
        self.start_time: Optional[str] = None
        self.current_question: str = ""
        self.current_strategy: str = ""

        # Recent history (last 100 Q&As visible via API)
        self.recent_entries: Deque[CognitionEntry] = deque(maxlen=100)

        # Seed topics for cold start (before memory has content)
        self._seed_topics = [
            "artificial intelligence", "consciousness", "quantum mechanics",
            "evolutionary biology", "information theory", "thermodynamics",
            "game theory", "neuroscience", "mathematics", "language",
            "ethics", "complexity theory", "emergence", "causality",
            "knowledge itself", "the nature of time", "computation",
        ]

        self._load_state()

    # ─── Control ───

    def start(self):
        if self.running:
            return
        self.running = True
        self.start_time = datetime.now().isoformat()
        self._task = asyncio.create_task(self._cognition_loop())
        logger.info("AutonomousCognitionEngine started — self-directed reasoning active")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._save_state()
        logger.info("AutonomousCognitionEngine stopped")

    # ─── Main Loop ───

    async def _cognition_loop(self):
        """
        The infinite self-directed reasoning loop.
        No sleep — runs as fast as the model allows.
        """
        logger.info("[Cognition] Loop started — generating first questions...")
        # Brief startup delay for model to be ready
        await asyncio.sleep(60)

        while self.running:
            try:
                await self._cognition_cycle()
                self.cycles_completed += 1
                # Save state periodically
                if self.cycles_completed % 10 == 0:
                    self._save_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Cognition] Cycle error: {e}")
                await asyncio.sleep(5)  # Brief pause on error, then continue

    async def _cognition_cycle(self):
        """One full cognition cycle: generate → answer → extract → store."""
        from lyra.core.engine import engine

        if not engine.loaded_model:
            await asyncio.sleep(10)
            return

        # PHASE 1: Replenish question queue if running low
        if len(self.question_queue) < 5:
            await self._generate_question_batch()

        # PHASE 2: Pick next question to answer
        if not self.question_queue:
            await self._generate_question_batch()
            return

        entry = self.question_queue.popleft()
        question = entry["question"]
        strategy = entry.get("strategy", "unknown")
        priority = entry.get("priority", 1)

        self.current_question = question
        self.current_strategy = strategy

        logger.info(f"[Cognition] [{strategy}] Answering: {question[:80]}...")

        # PHASE 3: Research — pull relevant context from memory
        context = await self._research_question(question)

        # PHASE 4: Answer the question
        answer = await self._answer_question(question, context, engine)
        if not answer or len(answer) < 50:
            return

        self.questions_answered += 1

        # PHASE 5: Store as learned knowledge
        await self._store_cognition(question, answer, strategy)

        # PHASE 6: Extract new questions from the answer
        new_questions = self._extract_new_questions(answer, strategy)
        for q in new_questions:
            self.question_queue.append({
                "question": q,
                "strategy": "extracted",
                "priority": priority + 1,  # Higher priority — directly derived
            })
            self.questions_generated += 1

        # Record in history
        self.recent_entries.appendleft(CognitionEntry(
            question=question,
            answer=answer[:500],
            strategy=strategy,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            tokens=len(answer.split()),
        ))

    # ─── Question Generation ───

    async def _generate_question_batch(self):
        """
        Generate a batch of questions using one of the 10 strategies.
        Picks topics from memory (if available) or seed topics.
        """
        from lyra.core.engine import engine

        if not engine.loaded_model:
            return

        # Pick strategy
        strategy_name = random.choice(list(QUESTION_STRATEGIES.keys()))
        template = QUESTION_STRATEGIES[strategy_name]

        # Get topics
        topics = await self._get_topics_for_strategy(strategy_name)
        if not topics:
            topics = [random.choice(self._seed_topics)]

        topic = topics[0]
        topic2 = topics[1] if len(topics) > 1 else random.choice(self._seed_topics)
        topics_str = ", ".join(topics[:5])

        prompt = template.format(
            topic=topic,
            topic2=topic2,
            topics=topics_str,
        )

        logger.info(f"[Cognition] Generating questions — strategy: {strategy_name}, topic: {topic}")

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You generate specific, intellectually interesting questions. "
                "Output ONLY a numbered list. No preamble."
            ),
            max_tokens=300,
            temperature=0.7,
            stream=True,
        ):
            parts.append(token)

        raw = "".join(parts).strip()
        questions = self._parse_question_list(raw)

        for q in questions:
            self.question_queue.append({
                "question": q,
                "strategy": strategy_name,
                "priority": 1,
            })
            self.questions_generated += 1

        if questions:
            logger.info(
                f"[Cognition] Generated {len(questions)} questions "
                f"({strategy_name} on '{topic}')"
            )

    async def _get_topics_for_strategy(self, strategy: str) -> List[str]:
        """Get relevant topics from memory for question generation."""
        try:
            from lyra.memory.vector_memory import memory
            from lyra.core.auto_learner import auto_learner

            # Primary: use highest-scored topics from auto-learner
            top = [t for t, _ in auto_learner.topic_scores.most_common(20)]
            if top:
                # Shuffle to ensure variety
                random.shuffle(top)
                return top[:5]

            # Fallback: search memory for any stored topics
            items = memory.retrieve(
                "knowledge topic subject", n_results=10, memory_type="learned_knowledge"
            )
            topics = []
            for item in items:
                t = item["metadata"].get("topic", "")
                if t and t not in topics:
                    topics.append(t)
            return topics[:5] if topics else [random.choice(self._seed_topics)]

        except Exception:
            return [random.choice(self._seed_topics)]

    # ─── Research ───

    async def _research_question(self, question: str) -> str:
        """Pull relevant context from memory to inform the answer."""
        try:
            from lyra.memory.vector_memory import memory

            sections = []

            # Synthesized wisdom (highest value)
            wisdom = memory.retrieve(question, n_results=2, memory_type="synthesized_wisdom")
            if wisdom:
                parts = ["\n[RELEVANT SYNTHESIZED KNOWLEDGE:]"]
                for item in wisdom[:2]:
                    parts.append(item["content"][:400])
                sections.append("\n".join(parts))

            # Learned knowledge
            facts = memory.retrieve(question, n_results=3, memory_type="learned_knowledge")
            if facts:
                parts = ["\n[RELEVANT FACTS:]"]
                for item in facts[:2]:
                    parts.append(f"• {item['content'][:300]}")
                sections.append("\n".join(parts))

            # Past cognition answers on similar questions
            past = memory.retrieve(question, n_results=2, memory_type="autonomous_cognition")
            if past:
                parts = ["\n[PAST SELF-REASONING ON THIS TOPIC:]"]
                for item in past[:1]:
                    parts.append(item["content"][:350])
                sections.append("\n".join(parts))

            return "\n".join(sections)

        except Exception:
            return ""

    # ─── Answer Generation ───

    async def _answer_question(self, question: str, context: str, engine) -> str:
        """Generate a thorough answer to the question."""
        system = ANSWER_SYSTEM_PROMPT
        if context:
            system += f"\n\nKNOWLEDGE CONTEXT:\n{context}"

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": question}],
            system_prompt=system,
            max_tokens=500,
            temperature=0.6,
            stream=True,
        ):
            parts.append(token)

        return "".join(parts).strip()

    # ─── Storage ───

    async def _store_cognition(self, question: str, answer: str, strategy: str):
        """Store the Q&A as autonomous cognition knowledge."""
        try:
            from lyra.memory.vector_memory import memory

            content = (
                f"[AUTONOMOUS COGNITION — {strategy.upper()} strategy]\n"
                f"Q: {question}\n\n"
                f"A: {answer}"
            )
            memory.store(
                content=content,
                memory_type="autonomous_cognition",
                metadata={
                    "strategy": strategy,
                    "question": question[:100],
                    "generated_at": datetime.now().isoformat(),
                    "importance": "6",
                },
            )

            # Also feed to auto-learner so topics get scored
            from lyra.core.auto_learner import auto_learner
            auto_learner.observe_message("user", question)

        except Exception as e:
            logger.debug(f"[Cognition] Storage failed: {e}")

    # ─── Question Extraction ───

    def _extract_new_questions(self, answer: str, parent_strategy: str) -> List[str]:
        """
        Extract follow-up questions from an answer.
        Looks for the FOLLOW-UP line we asked the model to include,
        plus any explicit questions in the text.
        """
        questions = []

        # Extract the FOLLOW-UP question we asked for
        for line in answer.split("\n"):
            if line.strip().startswith("FOLLOW-UP:"):
                q = line.replace("FOLLOW-UP:", "").strip()
                if len(q) > 10:
                    questions.append(q)
                break

        # Extract any inline questions (lines ending with ?)
        for line in answer.split("\n"):
            line = line.strip()
            if (
                line.endswith("?")
                and len(line) > 20
                and not line.startswith("FOLLOW-UP")
                and len(questions) < 3
            ):
                questions.append(line[:120])

        return questions[:3]

    def _parse_question_list(self, text: str) -> List[str]:
        """Parse a numbered list of questions from LLM output."""
        questions = []
        for line in text.split("\n"):
            line = line.strip().lstrip("0123456789.-) ")
            if len(line) > 15 and len(line) < 200:
                questions.append(line)
        return questions[:6]

    # ─── Status / API ───

    def get_status(self) -> Dict[str, Any]:
        """Return full status for the API endpoint."""
        recent = [
            {
                "question": e.question[:100],
                "answer": e.answer[:300],
                "strategy": e.strategy,
                "time": e.timestamp,
            }
            for e in list(self.recent_entries)[:20]
        ]
        return {
            "running": self.running,
            "questions_generated": self.questions_generated,
            "questions_answered": self.questions_answered,
            "cycles_completed": self.cycles_completed,
            "queue_depth": len(self.question_queue),
            "current_question": self.current_question[:100] if self.current_question else "",
            "current_strategy": self.current_strategy,
            "start_time": self.start_time,
            "recent_entries": recent,
            "strategies_available": list(QUESTION_STRATEGIES.keys()),
        }

    def inject_question(self, question: str, priority: int = 10):
        """Manually inject a question at high priority."""
        self.question_queue.appendleft({
            "question": question,
            "strategy": "manual_injection",
            "priority": priority,
        })
        self.questions_generated += 1
        logger.info(f"[Cognition] Manual question injected: {question[:60]}")

    # ─── Persistence ───

    def _save_state(self):
        try:
            state = {
                "questions_generated": self.questions_generated,
                "questions_answered": self.questions_answered,
                "cycles_completed": self.cycles_completed,
                "saved_at": datetime.now().isoformat(),
            }
            COGNITION_STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"[Cognition] State save failed: {e}")

    def _load_state(self):
        try:
            if COGNITION_STATE_FILE.exists():
                state = json.loads(COGNITION_STATE_FILE.read_text())
                self.questions_generated = state.get("questions_generated", 0)
                self.questions_answered = state.get("questions_answered", 0)
                self.cycles_completed = state.get("cycles_completed", 0)
                logger.info(
                    f"[Cognition] Loaded state: "
                    f"{self.questions_answered} questions answered historically"
                )
        except Exception as e:
            logger.debug(f"[Cognition] State load failed: {e}")


# Global singleton
cognition_engine = AutonomousCognitionEngine()
