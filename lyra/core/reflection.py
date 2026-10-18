"""
Lyra AI Platform — Self-Reflection & Quality Improvement System
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

After each response, Lyra evaluates its own answer quality.
High-quality reasoning patterns are stored as templates in memory.
These templates are later retrieved and injected into future prompts
as examples of excellent reasoning — creating a positive feedback loop
where Lyra continuously improves its own response quality over time.

The compounding effect: each high-quality response makes future responses
better by providing concrete examples of what "good" looks like.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Store as reasoning template if average quality score exceeds this threshold
QUALITY_THRESHOLD = 7.5


@dataclass
class ReflectionResult:
    score: float          # Average quality score (0-10)
    strengths: str        # What was done well
    weaknesses: str       # What could be improved
    stored: bool = False  # Whether this was stored as a template


class ResponseReflector:
    """
    Post-response self-evaluation system.

    Runs asynchronously after each response (never delays the user).
    For responses scoring >= 7.5/10, stores the Q&A pair as a reasoning
    template. Future conversations retrieve and inject these templates,
    giving the LLM concrete examples of its own best work.

    Over time: more good responses → more templates → better context →
    better responses → even more templates. Exponential quality growth.
    """

    def __init__(self):
        self.evaluations_run = 0
        self.templates_stored = 0

    async def evaluate_async(
        self,
        query: str,
        response: str,
        conversation_id: str = "",
    ):
        """
        Non-blocking quality evaluation — always called as a background task.
        Never delays user responses.
        """
        try:
            from lyra.core.engine import engine
            from lyra.memory.vector_memory import memory

            # Skip evaluation if model not loaded or response too short
            if not engine.loaded_model or len(response) < 120 or len(query) < 10:
                return

            result = await self._evaluate(query, response, engine)
            if result is None:
                return

            self.evaluations_run += 1

            if result.score >= QUALITY_THRESHOLD:
                await self._store_template(query, response, result, memory)
                result.stored = True
                self.templates_stored += 1
                logger.debug(
                    f"High-quality response stored as template "
                    f"(score={result.score:.1f})"
                )

        except Exception as e:
            logger.debug(f"Reflection evaluation failed: {e}")

    async def _evaluate(
        self, query: str, response: str, engine
    ) -> Optional[ReflectionResult]:
        """Use LLM to score response quality on four dimensions."""

        # Truncate to avoid excessive token use
        q_preview = query[:250]
        r_preview = response[:700]

        prompt = f"""Rate this AI response on 4 dimensions (1-10 each). Be a strict, honest critic.

QUESTION: {q_preview}

RESPONSE: {r_preview}

Score each (1=poor, 10=excellent):
- accuracy: Are facts correct and well-supported?
- completeness: Does it fully address the question?
- reasoning: Is the logic clear and well-structured?
- clarity: Is it easy to understand and well-written?

Also note one strength and one weakness.

Output ONLY valid JSON like this:
{{"accuracy": 8, "completeness": 7, "reasoning": 8, "clarity": 9, "strength": "one sentence", "weakness": "one sentence"}}"""

        parts = []
        async for token in engine.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You are a strict quality evaluator. Output ONLY valid JSON. "
                "No preamble, no explanation, just the JSON object."
            ),
            max_tokens=120,
            temperature=0.15,
            stream=True,
        ):
            parts.append(token)

        raw = "".join(parts).strip()

        try:
            import json
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            data = json.loads(raw[start:end])
            scores = [
                float(data.get("accuracy", 5)),
                float(data.get("completeness", 5)),
                float(data.get("reasoning", 5)),
                float(data.get("clarity", 5)),
            ]
            avg = sum(scores) / len(scores)
            return ReflectionResult(
                score=avg,
                strengths=str(data.get("strength", ""))[:120],
                weaknesses=str(data.get("weakness", ""))[:120],
            )
        except Exception:
            return None

    async def _store_template(
        self,
        query: str,
        response: str,
        result: ReflectionResult,
        memory,
    ):
        """Store a high-quality Q&A exchange as a reasoning template."""
        content = (
            f"[REASONING TEMPLATE — Quality Score: {result.score:.1f}/10]\n"
            f"Strength: {result.strengths}\n\n"
            f"EXAMPLE QUESTION:\n{query[:200]}\n\n"
            f"EXAMPLE HIGH-QUALITY RESPONSE:\n{response[:600]}"
        )
        memory.store(
            content=content,
            memory_type="reasoning_template",
            metadata={
                "score": str(round(result.score, 1)),
                "strength": result.strengths[:100],
                "stored_at": datetime.now().isoformat(),
                "importance": "9",
            },
        )

    async def get_template_context(self, query: str) -> str:
        """
        Retrieve a relevant reasoning template to inject into the system prompt.
        This is the core feedback mechanism — past successes improve future responses.
        """
        try:
            from lyra.memory.vector_memory import memory
            templates = memory.retrieve(
                query, n_results=2, memory_type="reasoning_template"
            )
            if not templates:
                return ""
            # Inject just the top template to avoid bloating the context
            best = templates[0]
            return (
                f"\n[REASONING EXAMPLE — from a previous high-quality response "
                f"(score {best['metadata'].get('score', '?')}/10):]"
                f"\n{best['content'][:420]}"
            )
        except Exception:
            return ""

    def get_status(self) -> dict:
        return {
            "evaluations_run": self.evaluations_run,
            "templates_stored": self.templates_stored,
            "quality_threshold": QUALITY_THRESHOLD,
        }


# Global singleton
reflector = ResponseReflector()
