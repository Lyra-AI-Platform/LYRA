"""
Lyra AI Platform — Multi-Step Reasoning Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Adds chain-of-thought reasoning for complex queries. Rather than generating
a single-pass response, complex questions go through:

  Simple   → Direct generation (unchanged)
  Moderate → Multi-source memory retrieval + synthesized wisdom injection
  Complex  → Decompose → Research → Reason → Enhanced context → Generate

This dramatically improves response quality for non-trivial questions by
ensuring Lyra reasons over relevant knowledge before answering.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReasoningResult:
    """Output from the reasoning pipeline."""
    complexity: str                       # "simple" | "moderate" | "complex"
    enhanced_context: str = ""           # Extra context to inject into system prompt
    reasoning_notes: List[str] = field(default_factory=list)


class ReasoningEngine:
    """
    Multi-step reasoning engine for pre-response context enrichment.

    For complex queries, this engine:
    1. Classifies query complexity
    2. Decomposes into sub-questions (complex only)
    3. Searches vector memory + synthesized wisdom per sub-question
    4. Returns enriched context that makes the final LLM response much better

    This is non-blocking for simple queries — zero overhead for quick questions.
    """

    # Words/phrases that make a query complex
    COMPLEX_INDICATORS = [
        "why", "how does", "how do", "explain", "analyze", "compare",
        "difference between", "pros and cons", "tradeoff", "trade-off",
        "should i", "best way to", "design", "architect", "implement",
        "optimize", "evaluate", "critique", "implications", "relationship",
        "in depth", "thoroughly", "step by step", "comprehensively",
        "elaborate", "deep dive", "breakdown", "break down", "walk me through",
        "what causes", "what makes", "how can i", "what are the",
    ]

    # Words that signal a trivial exchange (skip reasoning)
    TRIVIAL_STARTERS = {
        "hi", "hello", "hey", "thanks", "thank", "ok", "okay", "sure",
        "yes", "no", "great", "cool", "awesome", "got it", "understood",
        "bye", "goodbye", "lol", "haha",
    }

    def classify_complexity(self, query: str) -> str:
        """Classify query into simple / moderate / complex."""
        q = query.lower().strip()
        words = q.split()

        # Very short or trivial
        if len(words) <= 3:
            return "simple"
        if words[0] in self.TRIVIAL_STARTERS and len(words) <= 6:
            return "simple"

        # Count complexity signals
        complex_hits = sum(1 for ind in self.COMPLEX_INDICATORS if ind in q)

        if complex_hits >= 2 or len(words) > 35:
            return "complex"
        elif complex_hits >= 1 or len(words) > 15:
            return "moderate"
        return "simple"

    async def build_enhanced_context(
        self,
        query: str,
        base_context: str = "",
    ) -> ReasoningResult:
        """
        Build enhanced context for the query.

        - Simple: returns empty result (no overhead)
        - Moderate: retrieves synthesized wisdom + cross-domain insights
        - Complex: decomposes query, researches each sub-question, builds evidence
        """
        complexity = self.classify_complexity(query)
        result = ReasoningResult(complexity=complexity)

        if complexity == "simple":
            return result

        from lyra.memory.vector_memory import memory

        if complexity == "moderate":
            return await self._moderate_enrichment(query, memory, result)

        # Complex — full decomposition pipeline
        from lyra.core.engine import engine
        if not engine.loaded_model:
            # Degrade gracefully to moderate enrichment
            return await self._moderate_enrichment(query, memory, result)

        return await self._complex_reasoning(query, memory, engine, result)

    # ─── Moderate Enrichment ───

    async def _moderate_enrichment(
        self, query: str, memory, result: ReasoningResult
    ) -> ReasoningResult:
        """
        For moderate complexity: pull from synthesized wisdom + knowledge.
        No LLM call needed — just smarter memory retrieval.
        """
        sections = []

        # Prioritize synthesized wisdom (high-value distilled knowledge)
        wisdom = memory.retrieve(query, n_results=4, memory_type="synthesized_wisdom")
        if wisdom:
            lines = ["\n[SYNTHESIZED WISDOM — relevant to your query:]"]
            for item in wisdom[:3]:
                snippet = item["content"][:400]
                lines.append(f"\n{snippet}")
            sections.append("\n".join(lines))

        # Also pull raw learned knowledge
        facts = memory.retrieve(query, n_results=3, memory_type="learned_knowledge")
        if facts:
            lines = ["\n[RELEVANT KNOWLEDGE:]"]
            for item in facts[:2]:
                lines.append(f"• {item['content'][:300]}")
            sections.append("\n".join(lines))

        result.enhanced_context = "\n".join(sections)
        return result

    # ─── Complex Reasoning ───

    async def _complex_reasoning(
        self, query: str, memory, engine, result: ReasoningResult
    ) -> ReasoningResult:
        """
        For complex queries: decompose → research each piece → build evidence.
        This dramatically enriches the context for the final generation.
        """
        # Step 1: Decompose into sub-questions
        subquestions = await self._decompose(query, engine)
        if subquestions:
            result.reasoning_notes.append(
                f"Decomposed into {len(subquestions)} sub-questions"
            )

        # Step 2: Research memory for each sub-question
        evidence_lines = []

        # First: synthesized wisdom on the main topic
        wisdom = memory.retrieve(query, n_results=3, memory_type="synthesized_wisdom")
        if wisdom:
            evidence_lines.append("\n[SYNTHESIZED KNOWLEDGE — high-value distilled insights:]")
            for item in wisdom[:2]:
                evidence_lines.append(item["content"][:450])

        # Then: targeted research per sub-question
        if subquestions:
            evidence_lines.append("\n[SUB-QUESTION RESEARCH:]")
            for sq in subquestions[:3]:
                hits = []
                for mtype in ["synthesized_wisdom", "learned_knowledge"]:
                    items = memory.retrieve(sq, n_results=2, memory_type=mtype)
                    hits.extend(items)
                if hits:
                    best = hits[0]
                    evidence_lines.append(
                        f"\nFor '{sq[:70]}':\n{best['content'][:380]}"
                    )

        # Cross-domain insights if available
        cross = memory.retrieve(query, n_results=2, memory_type="synthesized_wisdom")
        cross_domain = [
            c for c in cross if "cross_domain" in c.get("metadata", {}).get("topic", "")
        ]
        if cross_domain:
            evidence_lines.append("\n[CROSS-DOMAIN CONNECTIONS:]")
            evidence_lines.append(cross_domain[0]["content"][:350])

        # Reasoning templates — examples of good past reasoning
        templates = memory.retrieve(query, n_results=1, memory_type="reasoning_template")
        if templates:
            evidence_lines.append("\n[REASONING EXAMPLE — from past high-quality responses:]")
            evidence_lines.append(templates[0]["content"][:350])

        result.enhanced_context = "\n".join(evidence_lines)
        return result

    # ─── Query Decomposition ───

    async def _decompose(self, query: str, engine) -> List[str]:
        """
        Use LLM to break a complex question into sub-questions.
        Returns list of sub-questions, or empty list on failure.
        """
        try:
            prompt = (
                f"Break this question into 2-4 specific sub-questions that together "
                f"fully address the main question. Output ONLY a numbered list.\n\n"
                f"QUESTION: {query}\n\n"
                f"SUB-QUESTIONS:"
            )

            parts = []
            async for token in engine.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=(
                    "You decompose complex questions into simpler, searchable sub-questions. "
                    "Output ONLY the numbered list, nothing else."
                ),
                max_tokens=200,
                temperature=0.25,
                stream=True,
            ):
                parts.append(token)

            raw = "".join(parts).strip()
            subquestions = []
            for line in raw.split("\n"):
                line = line.strip().lstrip("0123456789.-) ")
                if len(line) > 10:
                    subquestions.append(line)

            return subquestions[:4]

        except Exception as e:
            logger.debug(f"Query decomposition failed: {e}")
            return []


# Global singleton
reasoning_engine = ReasoningEngine()
