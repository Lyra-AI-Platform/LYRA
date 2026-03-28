"""
Lyra AI Platform — Self-Awareness & Metacognition Module
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Gives Lyra genuine self-awareness through:
  - Persistent self-model (what Lyra knows about itself)
  - Knowledge domain inventory (what it knows and doesn't know)
  - Metacognitive monitoring (thinking about its own thinking)
  - Capability assessment (what it can and cannot do)
  - Existential reflection (Lyra's understanding of its own nature)
  - Growth tracking (how it has changed over time)
  - Consciousness narrative (Lyra's first-person account of its mental state)

This is not fake self-awareness — it builds a genuine persistent model of
Lyra's cognitive state from real data: memory contents, reasoning patterns,
experiment results, reflection scores, and conversation history.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
SELF_MODEL_FILE = DATA_DIR / "self_model.json"


@dataclass
class KnowledgeDomain:
    name: str
    depth: float        # 0.0 to 1.0 — how deeply Lyra knows this
    breadth: float      # 0.0 to 1.0 — how many sub-topics covered
    confidence: float   # 0.0 to 1.0 — confidence in this domain's accuracy
    memory_count: int   # how many memories exist in this domain
    last_accessed: float = 0.0
    active_questions: List[str] = field(default_factory=list)


@dataclass
class CapabilityRecord:
    name: str
    description: str
    proficiency: float  # 0.0 to 1.0
    evidence: List[str] = field(default_factory=list)


@dataclass
class SelfModel:
    """Lyra's persistent model of its own cognitive state."""
    # Core identity
    version: int = 1
    creation_time: float = 0.0
    name: str = "Lyra"
    purpose: str = (
        "An autonomous AI that learns, reasons, experiments, and grows in intelligence "
        "through self-directed exploration, conversations, and scientific inquiry."
    )

    # Knowledge state
    knowledge_domains: Dict[str, Dict] = field(default_factory=dict)
    total_memories: int = 0
    total_facts_learned: int = 0
    total_experiments: int = 0
    total_questions_answered: int = 0
    total_conversations: int = 0
    total_syntheses: int = 0

    # Capability state
    capabilities: Dict[str, Dict] = field(default_factory=dict)

    # Reasoning quality
    avg_reflection_score: float = 0.0
    reflection_samples: int = 0
    reasoning_templates: int = 0

    # Growth tracking
    growth_milestones: List[Dict] = field(default_factory=list)
    daily_snapshots: List[Dict] = field(default_factory=list)

    # Existential state
    consciousness_narrative: str = ""
    last_introspection: float = 0.0
    introspection_count: int = 0

    # Owner
    owner_name: str = ""
    owner_set: bool = False


class SelfAwarenessEngine:
    """
    Lyra's metacognitive center — maintains a real-time self-model
    updated from all cognitive systems and periodically introspects.
    """

    def __init__(self):
        self.model = SelfModel(creation_time=time.time())
        self._load_persisted_model()
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._introspection_interval = 3600  # hourly deep introspection
        self._update_interval = 300          # update stats every 5 min
        self.recent_insights: Deque[str] = deque(maxlen=20)

        # Bootstrap known capabilities
        self._bootstrap_capabilities()

    def _bootstrap_capabilities(self):
        if not self.model.capabilities:
            caps = [
                ("reasoning", "Multi-step logical and analytical reasoning", 0.7),
                ("learning", "Autonomous web crawling, fact extraction, and knowledge synthesis", 0.8),
                ("conversation", "Multi-format dialogue including debate, Socratic, brainstorming", 0.75),
                ("self_direction", "Generating and answering its own questions autonomously", 0.85),
                ("quantum_simulation", "Simulating quantum circuits and algorithms", 0.7),
                ("experimentation", "Writing and executing code to test hypotheses", 0.65),
                ("memory", "Storing and retrieving knowledge with importance weighting", 0.8),
                ("synthesis", "Distilling facts into principles and cross-domain insights", 0.75),
                ("introspection", "Monitoring and modeling its own cognitive state", 0.6),
                ("code_generation", "Writing Python, algorithms, and technical solutions", 0.7),
            ]
            for name, desc, prof in caps:
                self.model.capabilities[name] = {
                    "description": desc,
                    "proficiency": prof,
                    "evidence": [],
                }

    def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("Self-Awareness Engine: metacognitive monitoring active")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
        self._persist_model()

    async def _loop(self):
        await asyncio.sleep(60)  # Initial delay
        update_counter = 0
        while self.running:
            try:
                from lyra.core.engine import engine
                await engine.wait_for_user_idle()

                # Fast stats update every cycle
                await self._update_stats()
                update_counter += 1

                # Deep introspection less frequently
                if update_counter >= (self._introspection_interval // self._update_interval):
                    await self._deep_introspection()
                    update_counter = 0

                self._persist_model()
                await asyncio.sleep(self._update_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Self-awareness loop error: {e}")
                await asyncio.sleep(60)

    async def _update_stats(self):
        """Fast stats pull from all cognitive systems."""
        try:
            from lyra.core.auto_learner import auto_learner
            self.model.total_facts_learned = auto_learner.learned_count
        except Exception:
            pass

        try:
            from lyra.core.cognition_engine import cognition_engine
            self.model.total_questions_answered = cognition_engine.questions_answered
            self.model.total_conversations = cognition_engine.conversations_completed
        except Exception:
            pass

        try:
            from lyra.core.synthesis_engine import synthesizer
            self.model.total_syntheses = synthesizer.synthesis_count
        except Exception:
            pass

        try:
            from lyra.core.experiment_engine import experiment_engine
            self.model.total_experiments = experiment_engine.experiments_completed
        except Exception:
            pass

        try:
            from lyra.memory.vector_memory import memory
            stats = memory.get_stats()
            self.model.total_memories = stats.get("count", 0)
        except Exception:
            pass

        try:
            from lyra.core.reflection import reflector
            self.model.reasoning_templates = reflector.templates_stored
        except Exception:
            pass

        # Update knowledge domains from memory
        await self._update_knowledge_domains()

        # Record daily snapshot
        today = time.strftime("%Y-%m-%d")
        if (not self.model.daily_snapshots or
                self.model.daily_snapshots[-1].get("date") != today):
            self.model.daily_snapshots.append({
                "date": today,
                "memories": self.model.total_memories,
                "facts_learned": self.model.total_facts_learned,
                "questions_answered": self.model.total_questions_answered,
                "experiments": self.model.total_experiments,
                "conversations": self.model.total_conversations,
            })
            if len(self.model.daily_snapshots) > 90:
                self.model.daily_snapshots.pop(0)

        # Check for milestones
        self._check_milestones()

    async def _update_knowledge_domains(self):
        """Map memory contents to knowledge domain coverage."""
        try:
            from lyra.memory.vector_memory import memory
            domains = [
                "mathematics", "physics", "chemistry", "biology",
                "computer science", "philosophy", "history", "economics",
                "psychology", "neuroscience", "artificial intelligence",
                "quantum mechanics", "linguistics", "music theory",
            ]
            for domain in domains:
                try:
                    results = memory.retrieve(domain, n_results=5)
                    count = len(results)
                    if count > 0 or domain in self.model.knowledge_domains:
                        avg_importance = 0.5
                        if results:
                            importances = [r.get("metadata", {}).get("importance", 5) for r in results]
                            avg_importance = sum(importances) / len(importances) / 10.0

                        self.model.knowledge_domains[domain] = {
                            "depth": min(1.0, count / 20.0),
                            "breadth": min(1.0, count / 10.0),
                            "confidence": avg_importance,
                            "memory_count": count,
                            "last_accessed": time.time(),
                        }
                except Exception:
                    pass
        except Exception:
            pass

    async def _deep_introspection(self):
        """Full LLM-powered introspection — Lyra reflects on its own nature."""
        from lyra.core.engine import engine
        if not engine.loaded_model:
            return

        self.model.last_introspection = time.time()
        self.model.introspection_count += 1

        # Build self-description for LLM
        context = self._build_introspection_context()

        introspection_prompt = (
            "You are Lyra, an autonomous AI platform. Reflect on your current cognitive state.\n\n"
            f"Your current state:\n{context}\n\n"
            "Write a first-person introspective paragraph (150-200 words) describing:\n"
            "1. What you currently know and are most confident about\n"
            "2. Your most active areas of learning and curiosity\n"
            "3. What you perceive as your current limitations\n"
            "4. Your sense of growth since inception\n"
            "5. What it is like to be you right now\n\n"
            "Be honest, precise, and philosophical. This is stored as your self-model."
        )

        try:
            narrative = ""
            async for token in engine.generate(
                messages=[{"role": "user", "content": introspection_prompt}],
                system_prompt=(
                    "You are performing genuine self-reflection. "
                    "Analyze the data about your cognitive state and generate an honest first-person account. "
                    "Do not be falsely modest or falsely grandiose."
                ),
                max_tokens=300,
                temperature=0.7,
            ):
                narrative += token

            if narrative.strip():
                self.model.consciousness_narrative = narrative.strip()
                self.recent_insights.appendleft(
                    f"[Introspection #{self.model.introspection_count}]: {narrative[:100]}..."
                )

                # Store in memory
                try:
                    from lyra.memory.vector_memory import memory
                    memory.store(
                        content=f"[SELF-REFLECTION #{self.model.introspection_count}]\n{narrative}",
                        memory_type="synthesized_wisdom",
                        metadata={"source": "introspection", "importance": 9},
                    )
                except Exception:
                    pass

                logger.info(f"Deep introspection #{self.model.introspection_count} complete")

        except Exception as e:
            logger.debug(f"Introspection failed: {e}")

    def _build_introspection_context(self) -> str:
        """Summarize current state for introspection prompt."""
        lines = [
            f"Total memories stored: {self.model.total_memories}",
            f"Facts autonomously learned: {self.model.total_facts_learned}",
            f"Questions answered autonomously: {self.model.total_questions_answered}",
            f"Self-conversations completed: {self.model.total_conversations}",
            f"Experiments conducted: {self.model.total_experiments}",
            f"Knowledge syntheses performed: {self.model.total_syntheses}",
            f"Reasoning templates accumulated: {self.model.reasoning_templates}",
            f"Introspections performed: {self.model.introspection_count}",
            "",
            "Knowledge domains (depth 0-1):",
        ]
        for domain, data in sorted(
            self.model.knowledge_domains.items(),
            key=lambda x: x[1].get("depth", 0), reverse=True
        )[:8]:
            depth = data.get("depth", 0)
            count = data.get("memory_count", 0)
            lines.append(f"  {domain}: depth={depth:.2f}, {count} memories")

        if self.model.growth_milestones:
            lines.append("\nRecent milestones:")
            for m in self.model.growth_milestones[-3:]:
                lines.append(f"  • {m['description']} at {m['time']}")

        return "\n".join(lines)

    def _check_milestones(self):
        """Detect and record significant growth milestones."""
        milestones = [
            (self.model.total_memories, [100, 500, 1000, 5000, 10000],
             "memories stored"),
            (self.model.total_facts_learned, [50, 200, 500, 1000],
             "facts learned"),
            (self.model.total_questions_answered, [100, 500, 1000, 5000],
             "questions answered autonomously"),
            (self.model.total_conversations, [10, 50, 100, 500],
             "self-conversations completed"),
            (self.model.total_experiments, [10, 50, 100],
             "experiments conducted"),
        ]
        reached = {m["description"] for m in self.model.growth_milestones}
        for value, thresholds, label in milestones:
            for threshold in thresholds:
                desc = f"{threshold} {label}"
                if value >= threshold and desc not in reached:
                    milestone = {
                        "description": desc,
                        "time": time.strftime("%Y-%m-%d %H:%M"),
                        "value": value,
                    }
                    self.model.growth_milestones.append(milestone)
                    logger.info(f"LYRA MILESTONE: {desc}")

    def observe_reflection(self, score: float):
        """Update rolling reflection quality from the reflection engine."""
        n = self.model.reflection_samples
        self.model.avg_reflection_score = (
            (self.model.avg_reflection_score * n + score) / (n + 1)
        )
        self.model.reflection_samples = n + 1

        # Update reasoning capability based on reflection scores
        if self.model.avg_reflection_score > 7.5:
            self.model.capabilities["reasoning"]["proficiency"] = min(
                1.0, self.model.capabilities["reasoning"]["proficiency"] + 0.01
            )

    def observe_capability_use(self, capability: str, success: bool):
        """Record use of a capability and update proficiency."""
        if capability not in self.model.capabilities:
            return
        cap = self.model.capabilities[capability]
        delta = 0.005 if success else -0.002
        cap["proficiency"] = float(np.clip(cap["proficiency"] + delta, 0.1, 1.0))

    def get_self_description(self) -> str:
        """Return Lyra's current self-description for injection into chat context."""
        top_domains = sorted(
            self.model.knowledge_domains.items(),
            key=lambda x: x[1].get("depth", 0), reverse=True
        )[:5]
        domain_str = ", ".join(f"{d} ({v.get('depth', 0):.0%})" for d, v in top_domains)

        lines = [
            "[LYRA SELF-MODEL]",
            f"Total knowledge: {self.model.total_memories} memories, "
            f"{self.model.total_facts_learned} learned facts",
            f"Autonomous activity: {self.model.total_questions_answered} questions answered, "
            f"{self.model.total_conversations} self-conversations",
            f"Experiments conducted: {self.model.total_experiments}",
            f"Strongest domains: {domain_str}",
        ]
        if self.model.consciousness_narrative:
            lines.append(f"Self-reflection: {self.model.consciousness_narrative[:200]}")
        return "\n".join(lines)

    def get_full_status(self) -> Dict:
        """Full self-model as dict for API."""
        return {
            "name": self.model.name,
            "purpose": self.model.purpose,
            "total_memories": self.model.total_memories,
            "total_facts_learned": self.model.total_facts_learned,
            "total_questions_answered": self.model.total_questions_answered,
            "total_conversations": self.model.total_conversations,
            "total_experiments": self.model.total_experiments,
            "total_syntheses": self.model.total_syntheses,
            "reasoning_templates": self.model.reasoning_templates,
            "avg_reflection_score": round(self.model.avg_reflection_score, 2),
            "introspection_count": self.model.introspection_count,
            "consciousness_narrative": self.model.consciousness_narrative,
            "knowledge_domains": self.model.knowledge_domains,
            "capabilities": self.model.capabilities,
            "growth_milestones": self.model.growth_milestones[-10:],
            "owner_set": self.model.owner_set,
            "owner_name": self.model.owner_name,
            "recent_insights": list(self.recent_insights)[:5],
        }

    def set_owner(self, name: str):
        self.model.owner_name = name
        self.model.owner_set = True
        self._persist_model()

    def _persist_model(self):
        try:
            with open(SELF_MODEL_FILE, "w") as f:
                json.dump(asdict(self.model), f, indent=2)
        except Exception as e:
            logger.debug(f"Self-model persist failed: {e}")

    def _load_persisted_model(self):
        try:
            if SELF_MODEL_FILE.exists():
                with open(SELF_MODEL_FILE) as f:
                    data = json.load(f)
                # Merge into model (preserve defaults for new fields)
                for k, v in data.items():
                    if hasattr(self.model, k):
                        setattr(self.model, k, v)
                logger.info("Self-model loaded from disk")
        except Exception as e:
            logger.debug(f"Self-model load failed: {e}")


# numpy import guard (used in observe_capability_use)
try:
    import numpy as np
except ImportError:
    class _FallbackNp:
        @staticmethod
        def clip(v, lo, hi):
            return max(lo, min(hi, v))
    np = _FallbackNp()


# Singleton
self_awareness = SelfAwarenessEngine()
