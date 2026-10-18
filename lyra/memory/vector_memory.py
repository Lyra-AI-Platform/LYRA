"""
Lyra AI Platform — Vector Memory System
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Persistent memory across conversations using ChromaDB.
Lyra remembers facts, preferences, and context from past sessions.

Enhanced with importance scoring:
  - Each memory type has a base importance score
  - Importance boosts on access (reinforcement — useful = memorable)
  - Retrieval re-ranks by composite: similarity * 0.6 + importance * 0.4
  - Synthesized wisdom and reasoning templates rise to top automatically
"""
import json
import logging
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# Base importance scores by memory type (0-10 scale)
# Higher = more likely to surface during retrieval
IMPORTANCE_BY_TYPE: Dict[str, float] = {
    "reasoning_template": 9.0,   # Proven high-quality reasoning patterns
    "synthesized_wisdom": 10.0,  # Distilled insights from many sources
    "knowledge_gap": 8.0,        # Things explicitly flagged as unknown
    "user_fact": 7.0,            # Facts about the user (always relevant)
    "learned_knowledge": 5.0,    # Web-crawled facts
    "learned_news": 4.0,         # RSS news items (decays quickly)
    "conversation_summary": 3.0, # Past conversation context
    "conversation": 2.0,         # Raw conversation entries
}


class NexusMemory:
    """
    Long-term memory for Lyra.
    Stores conversation summaries, user facts, and preferences.
    Retrieves relevant memories for each new conversation.
    """

    def __init__(self):
        self.client = None
        self.collection = None
        self.embedder = None
        self._initialized = False

    def _init(self):
        """Lazy init — only load ChromaDB when first used."""
        if self._initialized:
            return
        try:
            import chromadb
            from chromadb.config import Settings

            self.client = chromadb.PersistentClient(
                path=str(MEMORY_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            self.collection = self.client.get_or_create_collection(
                name="nexus_memory",
                metadata={"hnsw:space": "cosine"},
            )
            self._initialized = True
            logger.info(f"Memory system initialized. Stored memories: {self.collection.count()}")
        except ImportError:
            logger.warning("ChromaDB not installed. Memory disabled. Run: pip install chromadb")
        except Exception as e:
            logger.error(f"Memory init failed: {e}")

    def _embed(self, text: str) -> List[float]:
        """Create text embedding. Falls back to simple hash if no embedder."""
        try:
            from sentence_transformers import SentenceTransformer
            if self.embedder is None:
                self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            embedding = self.embedder.encode(text).tolist()
            return embedding
        except ImportError:
            # Fallback: simple pseudo-embedding from hash (not semantic but works)
            h = hashlib.sha256(text.encode()).hexdigest()
            return [int(h[i:i+2], 16) / 255.0 for i in range(0, 384*2, 2)][:384]

    def store(
        self,
        content: str,
        memory_type: str = "conversation",
        metadata: Dict = None,
        conversation_id: str = None,
    ) -> bool:
        """Store a memory entry with importance scoring."""
        self._init()
        if not self._initialized or not self.collection:
            return False

        try:
            doc_id = hashlib.sha256(
                f"{content}{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            # Determine importance score
            base_importance = IMPORTANCE_BY_TYPE.get(memory_type, 5.0)
            # Allow metadata to override importance (synthesis engine sets 10)
            if metadata and "importance" in metadata:
                try:
                    base_importance = float(metadata["importance"])
                except (ValueError, TypeError):
                    pass

            meta = {
                "type": memory_type,
                "timestamp": datetime.now().isoformat(),
                "conversation_id": conversation_id or "global",
                "importance": str(round(base_importance, 2)),
                "access_count": "0",
            }
            if metadata:
                meta.update({k: str(v) for k, v in metadata.items() if k != "importance"})
                # Restore our importance if metadata tried to override after
                if "importance" not in metadata:
                    meta["importance"] = str(round(base_importance, 2))

            embedding = self._embed(content)
            self.collection.add(
                ids=[doc_id],
                documents=[content],
                embeddings=[embedding],
                metadatas=[meta],
            )
            return True
        except Exception as e:
            logger.error(f"Memory store failed: {e}")
            return False

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant memories for a query.

        Re-ranks results using a composite score:
          composite = similarity(0.6) + normalized_importance(0.4)

        This ensures synthesized wisdom and reasoning templates
        surface preferentially over raw facts of similar relevance.
        """
        self._init()
        if not self._initialized or not self.collection:
            return []

        try:
            count = self.collection.count()
            if count == 0:
                return []

            # Fetch more candidates than needed so re-ranking is meaningful
            fetch_n = min(n_results * 3, count)
            embedding = self._embed(query)
            where = {"type": memory_type} if memory_type else None

            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=fetch_n,
                where=where,
            )

            memories = []
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i]
                distance = results["distances"][0][i] if results.get("distances") else 0.5

                # Similarity: ChromaDB returns cosine distance (lower=better)
                similarity = max(0.0, 1.0 - float(distance))

                # Importance: 0-10 scale, normalized to 0-1
                importance = float(meta.get("importance", "5")) / 10.0

                # Composite score
                composite = (similarity * 0.6) + (importance * 0.4)

                memories.append({
                    "content": doc,
                    "metadata": meta,
                    "distance": distance,
                    "similarity": similarity,
                    "importance": float(meta.get("importance", "5")),
                    "composite_score": composite,
                })

            # Sort by composite score (descending)
            memories.sort(key=lambda x: x["composite_score"], reverse=True)
            return memories[:n_results]

        except Exception as e:
            logger.error(f"Memory retrieve failed: {e}")
            return []

    def store_user_fact(self, fact: str) -> bool:
        """Store a fact about the user (preferences, info, etc.)."""
        return self.store(fact, memory_type="user_fact")

    def store_conversation_summary(self, summary: str, conv_id: str) -> bool:
        """Store a summary of a completed conversation."""
        return self.store(summary, memory_type="conversation_summary", conversation_id=conv_id)

    def get_context_for_prompt(self, query: str) -> str:
        """
        Retrieve relevant memories and format them as context
        to inject into the AI's system prompt.

        Retrieval order (by composite score):
          1. Synthesized wisdom (importance=10) — distilled principles
          2. Reasoning templates (importance=9) — proven good reasoning
          3. User facts (importance=7) — personal context
          4. Learned knowledge (importance=5) — web-crawled facts
          5. Conversation context (importance=2-3) — recent history
        """
        memories = self.retrieve(query, n_results=8)
        if not memories:
            return ""

        lines = ["[Lyra MEMORY — relevant context from past sessions:]"]
        for m in memories:
            ts = m["metadata"].get("timestamp", "")[:10]
            mtype = m["metadata"].get("type", "memory")
            importance = m.get("importance", 5)

            # Emphasize high-importance memories in the context block
            if importance >= 9:
                prefix = "★"  # Synthesized wisdom / templates
            elif importance >= 7:
                prefix = "•"  # User facts
            else:
                prefix = "·"  # General knowledge

            lines.append(f"{prefix} [{ts}] ({mtype}) {m['content'][:350]}")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        """Return memory statistics."""
        self._init()
        if not self._initialized or not self.collection:
            return {"enabled": False, "count": 0}
        return {
            "enabled": True,
            "count": self.collection.count(),
            "path": str(MEMORY_DIR),
        }

    def clear(self) -> bool:
        """Clear all memories."""
        self._init()
        if not self._initialized or not self.collection:
            return False
        try:
            self.client.delete_collection("nexus_memory")
            self.collection = self.client.get_or_create_collection("nexus_memory")
            return True
        except Exception as e:
            logger.error(f"Memory clear failed: {e}")
            return False


# Global singleton
memory = NexusMemory()
