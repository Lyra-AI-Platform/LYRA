"""
Lyra AI Platform — Autonomous Cognition Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Fully autonomous self-directed cognition loop.
Runs continuously in the background. Instantly yields to real user requests.

TWO MODES, alternating:

  1. SELF-Q&A  — generates questions and answers them (original mode)
  2. SELF-CONVERSATION — full multi-turn dialogues with itself

Six conversation formats:

  DEBATE           Two voices argue opposing positions on a topic
  SOCRATIC         A questioner draws out deeper understanding through questions
  BRAINSTORM       Two creative voices riff, build, and combine ideas freely
  TEACHING         Professor explains; student asks until they understand
  THOUGHT_EXPERIMENT  Philosophers explore a hypothetical together
  PEER_REVIEW      One voice presents ideas; the other critiques rigorously

Why conversations beat single Q&A:
  - Disagreement forces deeper reasoning than agreement
  - Questions beget better questions
  - Multi-turn context builds richer understanding
  - Communication patterns stored in memory improve human chat responses
  - Each voice can specialize (creative vs critical, broad vs deep)

USER PRIORITY: whenever a human sends a message, background inference
immediately yields. The user never waits for background thinking.
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

# ── How often to do a full conversation vs single Q&A ──
# 1 = every cycle is a conversation, 3 = every 3rd cycle
CONVERSATION_FREQUENCY = 2


# ════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ════════════════════════════════════════════════════════════

@dataclass
class CognitionEntry:
    question: str
    answer: str
    strategy: str
    timestamp: str
    tokens: int = 0


@dataclass
class ConversationTurn:
    voice: str       # e.g. "LYRA-A", "LYRA-B", "PROFESSOR", "STUDENT"
    content: str


@dataclass
class SelfConversation:
    format: str
    topic: str
    turns: List[ConversationTurn]
    insights: List[str]
    new_questions: List[str]
    timestamp: str


# ════════════════════════════════════════════════════════════
#  QUESTION STRATEGIES (for Q&A mode)
# ════════════════════════════════════════════════════════════

QUESTION_STRATEGIES = {
    "gaps": (
        "Topic: '{topic}'\n"
        "List 4 specific things about this topic that are unclear, uncertain, "
        "or worth deeper investigation. Number them."
    ),
    "depth": (
        "Topic: '{topic}'\n"
        "Generate 4 'how exactly' questions forcing step-by-step mechanistic "
        "explanations. Number them."
    ),
    "connections": (
        "Topics: '{topic}' and '{topic2}'\n"
        "Generate 4 questions about non-obvious connections, analogies, or shared "
        "principles between these topics. Number them."
    ),
    "critiques": (
        "Topic: '{topic}'\n"
        "Generate 4 critical questions: weaknesses, limits, counterarguments, "
        "common misconceptions. Number them."
    ),
    "frontiers": (
        "Topic: '{topic}'\n"
        "Generate 4 frontier questions: what is unsolved, actively debated, or "
        "on the cutting edge. Number them."
    ),
    "applications": (
        "Topic: '{topic}'\n"
        "Generate 4 questions: where does this matter in practice? Who uses it? "
        "What problems does it solve? Number them."
    ),
    "history": (
        "Topic: '{topic}'\n"
        "Generate 4 historical questions: how did this develop? Key breakthroughs? "
        "What changed? Number them."
    ),
    "predictions": (
        "Topic: '{topic}'\n"
        "Generate 4 forward-looking questions: where is this heading? "
        "Emerging trends? Future state? Number them."
    ),
    "fundamentals": (
        "Topic: '{topic}'\n"
        "Generate 4 first-principles questions: core assumptions, foundations, "
        "what must be true for this to hold. Number them."
    ),
    "synthesis": (
        "Topics: {topics}\n"
        "Generate 4 cross-domain synthesis questions combining multiple topics "
        "to find emergent patterns. Number them."
    ),
}

ANSWER_SYSTEM = """You are an autonomous intelligence exploring your own knowledge.
Answer the question thoroughly and insightfully (150-300 words).
Go beyond facts — explain mechanisms, implications, and connections.
Note uncertainty explicitly when present.
End with: FOLLOW-UP: [one specific question this answer raises]"""


# ════════════════════════════════════════════════════════════
#  CONVERSATION FORMATS
# ════════════════════════════════════════════════════════════

CONVERSATION_FORMATS = {

    "debate": {
        "description": "Two voices argue opposing positions — one defends, one attacks",
        "voices": ["LYRA-PRO", "LYRA-CON"],
        "setup_prompt": (
            "Topic: '{topic}'\n\n"
            "You will generate a structured debate between two voices:\n"
            "LYRA-PRO: Argues in favor of / for the strongest case for this topic\n"
            "LYRA-CON: Argues against / challenges the strongest case\n\n"
            "Generate {turns} alternating turns. Each turn: 2-4 sentences. "
            "Each voice must engage with what the other just said — no monologues.\n"
            "Format strictly as:\nLYRA-PRO: ...\nLYRA-CON: ...\n(repeat)"
        ),
        "turns": 8,
    },

    "socratic": {
        "description": "A questioner draws out deeper understanding through questions alone",
        "voices": ["QUESTIONER", "THINKER"],
        "setup_prompt": (
            "Topic: '{topic}'\n\n"
            "QUESTIONER only asks questions — never gives answers or opinions.\n"
            "THINKER answers and reflects, but QUESTIONER's next question must "
            "challenge or deepen the previous answer.\n\n"
            "Generate {turns} turns. QUESTIONER uses the Socratic method to lead "
            "THINKER to discover deeper truths and contradictions.\n"
            "Format:\nQUESTIONER: ...\nTHINKER: ...\n(repeat)"
        ),
        "turns": 8,
    },

    "brainstorm": {
        "description": "Two creative voices riff, build, and combine ideas freely",
        "voices": ["LYRA-A", "LYRA-B"],
        "setup_prompt": (
            "Topic: '{topic}'\n\n"
            "Two creative minds brainstorm together. Rules:\n"
            "- Yes, and... — always build on the previous idea, never block it\n"
            "- Make surprising connections to other fields\n"
            "- Get more specific with each turn\n"
            "- End each turn with a new direction to explore\n\n"
            "Generate {turns} turns of rapid-fire creative exchange.\n"
            "Format:\nLYRA-A: ...\nLYRA-B: ...\n(repeat)"
        ),
        "turns": 8,
    },

    "teaching": {
        "description": "Professor explains; student asks until they truly understand",
        "voices": ["PROFESSOR", "STUDENT"],
        "setup_prompt": (
            "Topic: '{topic}'\n\n"
            "PROFESSOR explains clearly with examples and analogies.\n"
            "STUDENT asks honest questions — what's unclear, what's assumed, "
            "what connects to other things they know.\n"
            "PROFESSOR must adapt to each question — go deeper, use better analogies.\n\n"
            "Start: PROFESSOR gives a 3-sentence opening explanation.\n"
            "Generate {turns} turns total.\n"
            "Format:\nPROFESSOR: ...\nSTUDENT: ...\n(repeat)"
        ),
        "turns": 8,
    },

    "thought_experiment": {
        "description": "Two philosophers explore a hypothetical scenario together",
        "voices": ["PHILOSOPHER-A", "PHILOSOPHER-B"],
        "setup_prompt": (
            "Topic: '{topic}'\n\n"
            "Design a thought experiment around this topic and explore it together.\n"
            "PHILOSOPHER-A: Proposes and defends the scenario's premises\n"
            "PHILOSOPHER-B: Tests edge cases, finds paradoxes, extends the scenario\n\n"
            "Both must be intellectually honest — update their views when "
            "presented with strong arguments.\n"
            "Generate {turns} turns of rigorous philosophical exploration.\n"
            "Format:\nPHILOSOPHER-A: ...\nPHILOSOPHER-B: ...\n(repeat)"
        ),
        "turns": 8,
    },

    "peer_review": {
        "description": "One voice presents ideas; the other critiques rigorously",
        "voices": ["PRESENTER", "REVIEWER"],
        "setup_prompt": (
            "Topic: '{topic}'\n\n"
            "PRESENTER shares a claim, idea, or finding about this topic.\n"
            "REVIEWER asks hard questions: What's the evidence? "
            "What are alternative explanations? What are the limits?\n"
            "PRESENTER must defend or revise based on the critique.\n\n"
            "This is a rigorous intellectual peer review — no softening.\n"
            "Generate {turns} turns.\n"
            "Format:\nPRESENTER: ...\nREVIEWER: ...\n(repeat)"
        ),
        "turns": 8,
    },
}

INSIGHT_EXTRACTION_PROMPT = """Read this self-conversation and extract:

CONVERSATION:
{conversation}

Output JSON only:
{{
  "key_insights": ["insight 1", "insight 2", "insight 3"],
  "unresolved_questions": ["question 1", "question 2"],
  "strongest_argument": "one sentence summary",
  "what_changed": "what understanding shifted during this conversation"
}}"""


# ════════════════════════════════════════════════════════════
#  MAIN ENGINE
# ════════════════════════════════════════════════════════════

class AutonomousCognitionEngine:
    """
    Alternates between single Q&A cycles and full self-conversations.
    Instantly yields to user requests. Runs otherwise continuously.
    """

    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0

        # Q&A queue
        self.question_queue: Deque[Dict] = deque(maxlen=500)

        # Stats
        self.questions_generated: int = 0
        self.questions_answered: int = 0
        self.conversations_completed: int = 0
        self.cycles_completed: int = 0
        self.start_time: Optional[str] = None
        self.current_question: str = ""
        self.current_strategy: str = ""
        self.current_activity: str = "idle"

        # Recent history
        self.recent_entries: Deque[CognitionEntry] = deque(maxlen=50)
        self.recent_conversations: Deque[Dict] = deque(maxlen=20)

        self._seed_topics = [
            "artificial intelligence", "consciousness", "quantum mechanics",
            "evolutionary biology", "information theory", "thermodynamics",
            "game theory", "neuroscience", "mathematics", "language",
            "ethics", "complexity theory", "emergence", "causality",
            "the nature of time", "computation", "knowledge", "creativity",
        ]

        self._load_state()

    # ─── Control ───

    def start(self):
        if self.running:
            return
        self.running = True
        self.start_time = datetime.now().isoformat()
        self._task = asyncio.create_task(self._loop())
        logger.info("AutonomousCognitionEngine started — Q&A + self-conversations active")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._save_state()

    # ─── Main Loop ───

    async def _loop(self):
        logger.info("[Cognition] Starting up — waiting 90s for system to initialize...")
        await asyncio.sleep(90)

        while self.running:
            try:
                from lyra.core.engine import engine
                # Always yield to user first
                await engine.wait_for_user_idle()

                self._cycle_count += 1

                # Alternate: every Nth cycle do a full conversation
                if self._cycle_count % CONVERSATION_FREQUENCY == 0:
                    await self._run_conversation_cycle()
                else:
                    await self._run_qa_cycle()

                self.cycles_completed += 1
                if self.cycles_completed % 10 == 0:
                    self._save_state()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Cognition] Loop error: {e}")
                await asyncio.sleep(5)

    # ════════════════════════════════════════════════════════
    #  SELF-CONVERSATION MODE
    # ════════════════════════════════════════════════════════

    async def _run_conversation_cycle(self):
        from lyra.core.engine import engine
        if not engine.loaded_model:
            await asyncio.sleep(10)
            return

        fmt_name = random.choice(list(CONVERSATION_FORMATS.keys()))
        fmt = CONVERSATION_FORMATS[fmt_name]
        topic = await self._pick_topic()

        self.current_activity = f"💬 Self-conversation [{fmt_name}] on '{topic[:40]}'"
        self.current_strategy = fmt_name
        logger.info(f"[Cognition] Starting {fmt_name} conversation on: {topic}")

        # Generate the full conversation in one LLM call
        await engine.wait_for_user_idle()

        prompt = fmt["setup_prompt"].format(
            topic=topic,
            turns=fmt["turns"],
        )

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You are Lyra generating an internal self-conversation. "
                "Follow the format exactly. Be intellectually rigorous and honest. "
                "Let the conversation evolve naturally — voices can change their minds."
            ),
            max_tokens=1200,
            temperature=0.75,
            stream=True,
        ):
            # Yield to user immediately if they send a message
            if engine.user_active.is_set():
                parts = []  # discard incomplete conversation
                return
            parts.append(token)

        raw_conversation = "".join(parts).strip()
        if len(raw_conversation) < 200:
            return

        # Parse turns from the raw text
        turns = self._parse_conversation_turns(raw_conversation, fmt["voices"])

        # Extract insights
        await engine.wait_for_user_idle()
        insights, new_questions = await self._extract_insights(
            raw_conversation, engine
        )

        # Store the full conversation
        convo = SelfConversation(
            format=fmt_name,
            topic=topic,
            turns=turns,
            insights=insights,
            new_questions=new_questions,
            timestamp=datetime.now().strftime("%H:%M:%S"),
        )
        await self._store_conversation(convo)

        # Feed new questions into the Q&A queue
        for q in new_questions:
            self.question_queue.append({
                "question": q,
                "strategy": f"from_{fmt_name}",
                "priority": 3,
            })
            self.questions_generated += 1

        self.conversations_completed += 1
        self.current_activity = f"idle (last: {fmt_name} on '{topic[:30]}')"

        # Store in recent history for the API
        self.recent_conversations.appendleft({
            "format": fmt_name,
            "topic": topic,
            "turns": len(turns),
            "insights": insights[:2],
            "new_questions": new_questions[:2],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "preview": raw_conversation[:600],
        })

        logger.info(
            f"[Cognition] {fmt_name} done — {len(turns)} turns, "
            f"{len(insights)} insights, {len(new_questions)} new questions"
        )

    def _parse_conversation_turns(
        self, raw: str, voices: List[str]
    ) -> List[ConversationTurn]:
        """Parse 'VOICE: content' lines into ConversationTurn objects."""
        turns = []
        current_voice = None
        current_lines = []

        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            matched = False
            for voice in voices:
                if line.upper().startswith(f"{voice}:"):
                    # Save previous turn
                    if current_voice and current_lines:
                        turns.append(ConversationTurn(
                            voice=current_voice,
                            content=" ".join(current_lines).strip(),
                        ))
                    current_voice = voice
                    current_lines = [line[len(voice) + 1:].strip()]
                    matched = True
                    break
            if not matched and current_voice:
                current_lines.append(line)

        if current_voice and current_lines:
            turns.append(ConversationTurn(
                voice=current_voice,
                content=" ".join(current_lines).strip(),
            ))

        return turns

    async def _extract_insights(
        self, conversation: str, engine
    ):
        """Use LLM to extract key insights and new questions from a conversation."""
        await engine.wait_for_user_idle()
        if engine.user_active.is_set():
            return [], []

        prompt = INSIGHT_EXTRACTION_PROMPT.format(
            conversation=conversation[:2000]
        )
        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="Extract insights from a conversation. Output only valid JSON.",
            max_tokens=300,
            temperature=0.2,
            stream=True,
        ):
            if engine.user_active.is_set():
                break
            parts.append(token)

        raw = "".join(parts).strip()
        insights, questions = [], []
        try:
            import json as _json
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = _json.loads(raw[start:end])
                insights = [str(i) for i in data.get("key_insights", [])[:3]]
                questions = [str(q) for q in data.get("unresolved_questions", [])[:3]]
        except Exception:
            pass
        return insights, questions

    async def _store_conversation(self, convo: SelfConversation):
        """Store a completed self-conversation in vector memory."""
        try:
            from lyra.memory.vector_memory import memory

            # Store full conversation text
            turns_text = "\n".join(
                f"{t.voice}: {t.content}" for t in convo.turns
            )
            content = (
                f"[SELF-CONVERSATION — {convo.format.upper()} format]\n"
                f"Topic: {convo.topic}\n"
                f"Date: {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"{turns_text}"
            )
            memory.store(
                content=content,
                memory_type="self_conversation",
                metadata={
                    "format": convo.format,
                    "topic": convo.topic,
                    "turn_count": str(len(convo.turns)),
                    "importance": "7",
                    "stored_at": datetime.now().isoformat(),
                },
            )

            # Store insights separately as high-importance synthesized wisdom
            if convo.insights:
                insight_text = (
                    f"[CONVERSATION INSIGHTS — {convo.format.upper()} on '{convo.topic}']\n\n"
                    + "\n".join(f"• {i}" for i in convo.insights)
                )
                memory.store(
                    content=insight_text,
                    memory_type="synthesized_wisdom",
                    metadata={
                        "topic": convo.topic,
                        "source": f"self_conversation_{convo.format}",
                        "importance": "8",
                        "stored_at": datetime.now().isoformat(),
                    },
                )
        except Exception as e:
            logger.debug(f"[Cognition] Conversation storage failed: {e}")

    # ════════════════════════════════════════════════════════
    #  Q&A MODE
    # ════════════════════════════════════════════════════════

    async def _run_qa_cycle(self):
        from lyra.core.engine import engine
        if not engine.loaded_model:
            await asyncio.sleep(10)
            return

        # Replenish queue
        if len(self.question_queue) < 5:
            await engine.wait_for_user_idle()
            await self._generate_question_batch()

        if not self.question_queue:
            return

        entry = self.question_queue.popleft()
        question = entry["question"]
        strategy = entry.get("strategy", "unknown")

        self.current_question = question
        self.current_strategy = strategy
        self.current_activity = f"🤔 [{strategy}] {question[:60]}..."

        await engine.wait_for_user_idle()
        context = await self._research(question)

        await engine.wait_for_user_idle()
        if engine.user_active.is_set():
            self.question_queue.appendleft(entry)  # put it back
            return

        answer = await self._answer(question, context, engine)
        if not answer or len(answer) < 50:
            return

        self.questions_answered += 1
        await self._store_qa(question, answer, strategy)

        new_qs = self._extract_questions_from_answer(answer)
        for q in new_qs:
            self.question_queue.append({"question": q, "strategy": "extracted", "priority": 2})
            self.questions_generated += 1

        self.recent_entries.appendleft(CognitionEntry(
            question=question,
            answer=answer[:500],
            strategy=strategy,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            tokens=len(answer.split()),
        ))

    async def _generate_question_batch(self):
        from lyra.core.engine import engine
        if not engine.loaded_model:
            return

        strategy_name = random.choice(list(QUESTION_STRATEGIES.keys()))
        template = QUESTION_STRATEGIES[strategy_name]
        topics = await self._get_topics()

        topic = topics[0] if topics else random.choice(self._seed_topics)
        topic2 = topics[1] if len(topics) > 1 else random.choice(self._seed_topics)
        topics_str = ", ".join(topics[:5])

        prompt = template.format(topic=topic, topic2=topic2, topics=topics_str)

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="Generate specific questions. Output ONLY a numbered list.",
            max_tokens=280,
            temperature=0.7,
            stream=True,
        ):
            if engine.user_active.is_set():
                return
            parts.append(token)

        for q in self._parse_list("".join(parts)):
            self.question_queue.append({"question": q, "strategy": strategy_name, "priority": 1})
            self.questions_generated += 1

    async def _research(self, question: str) -> str:
        try:
            from lyra.memory.vector_memory import memory
            sections = []
            for mtype in ["synthesized_wisdom", "learned_knowledge", "self_conversation"]:
                items = memory.retrieve(question, n_results=2, memory_type=mtype)
                if items:
                    lines = [f"\n[{mtype.upper()}:]"]
                    lines += [f"• {i['content'][:320]}" for i in items[:1]]
                    sections.append("\n".join(lines))
            return "\n".join(sections)
        except Exception:
            return ""

    async def _answer(self, question: str, context: str, engine) -> str:
        system = ANSWER_SYSTEM
        if context:
            system += f"\n\nCONTEXT:\n{context}"
        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": question}],
            system_prompt=system,
            max_tokens=480,
            temperature=0.6,
            stream=True,
        ):
            if engine.user_active.is_set():
                return ""
            parts.append(token)
        return "".join(parts).strip()

    async def _store_qa(self, question: str, answer: str, strategy: str):
        try:
            from lyra.memory.vector_memory import memory
            memory.store(
                content=(
                    f"[AUTONOMOUS Q&A — {strategy}]\n"
                    f"Q: {question}\nA: {answer}"
                ),
                memory_type="autonomous_cognition",
                metadata={
                    "strategy": strategy,
                    "question": question[:100],
                    "importance": "6",
                    "stored_at": datetime.now().isoformat(),
                },
            )
            from lyra.core.auto_learner import auto_learner
            auto_learner.observe_message("user", question)
        except Exception as e:
            logger.debug(f"[Cognition] Q&A storage failed: {e}")

    def _extract_questions_from_answer(self, answer: str) -> List[str]:
        questions = []
        for line in answer.split("\n"):
            if line.strip().startswith("FOLLOW-UP:"):
                q = line.replace("FOLLOW-UP:", "").strip()
                if len(q) > 10:
                    questions.append(q)
                break
        for line in answer.split("\n"):
            line = line.strip()
            if line.endswith("?") and len(line) > 20 and len(questions) < 3:
                questions.append(line[:120])
        return questions[:3]

    # ─── Helpers ───

    async def _pick_topic(self) -> str:
        topics = await self._get_topics()
        return topics[0] if topics else random.choice(self._seed_topics)

    async def _get_topics(self) -> List[str]:
        try:
            from lyra.core.auto_learner import auto_learner
            top = [t for t, _ in auto_learner.topic_scores.most_common(20)]
            if top:
                random.shuffle(top)
                return top[:5]
            from lyra.memory.vector_memory import memory
            items = memory.retrieve("knowledge topic", n_results=8, memory_type="learned_knowledge")
            topics = list({i["metadata"].get("topic", "") for i in items if i["metadata"].get("topic")})
            return topics[:5] if topics else [random.choice(self._seed_topics)]
        except Exception:
            return [random.choice(self._seed_topics)]

    def _parse_list(self, text: str) -> List[str]:
        result = []
        for line in text.split("\n"):
            line = line.strip().lstrip("0123456789.-) ")
            if 15 < len(line) < 200:
                result.append(line)
        return result[:6]

    # ─── Status / API ───

    def get_status(self) -> Dict[str, Any]:
        recent_qa = [
            {"question": e.question[:100], "answer": e.answer[:300],
             "strategy": e.strategy, "time": e.timestamp}
            for e in list(self.recent_entries)[:10]
        ]
        recent_convos = list(self.recent_conversations)[:5]
        return {
            "running": self.running,
            "current_activity": self.current_activity,
            "questions_generated": self.questions_generated,
            "questions_answered": self.questions_answered,
            "conversations_completed": self.conversations_completed,
            "cycles_completed": self.cycles_completed,
            "queue_depth": len(self.question_queue),
            "current_question": self.current_question[:100],
            "current_strategy": self.current_strategy,
            "start_time": self.start_time,
            "recent_qa": recent_qa,
            "recent_conversations": recent_convos,
            "conversation_formats": list(CONVERSATION_FORMATS.keys()),
            "qa_strategies": list(QUESTION_STRATEGIES.keys()),
        }

    def inject_question(self, question: str, priority: int = 10):
        self.question_queue.appendleft(
            {"question": question, "strategy": "manual", "priority": priority}
        )
        self.questions_generated += 1
        logger.info(f"[Cognition] Manual question injected: {question[:60]}")

    async def trigger_conversation(self, topic: str = "", fmt: str = "") -> Dict:
        """Manually trigger a self-conversation on demand."""
        from lyra.core.engine import engine
        if not engine.loaded_model:
            return {"success": False, "error": "No model loaded"}

        fmt_name = fmt if fmt in CONVERSATION_FORMATS else random.choice(list(CONVERSATION_FORMATS.keys()))
        if not topic:
            topic = await self._pick_topic()

        old_activity = self.current_activity
        await self._run_conversation_cycle()
        return {
            "success": True,
            "format": fmt_name,
            "topic": topic,
            "conversations_completed": self.conversations_completed,
        }

    # ─── Persistence ───

    def _save_state(self):
        try:
            COGNITION_STATE_FILE.write_text(json.dumps({
                "questions_generated": self.questions_generated,
                "questions_answered": self.questions_answered,
                "conversations_completed": self.conversations_completed,
                "cycles_completed": self.cycles_completed,
                "saved_at": datetime.now().isoformat(),
            }, indent=2))
        except Exception:
            pass

    def _load_state(self):
        try:
            if COGNITION_STATE_FILE.exists():
                s = json.loads(COGNITION_STATE_FILE.read_text())
                self.questions_generated = s.get("questions_generated", 0)
                self.questions_answered = s.get("questions_answered", 0)
                self.conversations_completed = s.get("conversations_completed", 0)
                self.cycles_completed = s.get("cycles_completed", 0)
                logger.info(
                    f"[Cognition] Restored: {self.questions_answered} Q&As, "
                    f"{self.conversations_completed} conversations"
                )
        except Exception:
            pass


# Global singleton
cognition_engine = AutonomousCognitionEngine()
