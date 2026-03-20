"""
NEXUS Vector Memory System
Persistent memory across conversations using ChromaDB.
NEXUS remembers facts, preferences, and context from past sessions.
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


class NexusMemory:
    """
    Long-term memory for NEXUS.
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
        """Store a memory entry."""
        self._init()
        if not self._initialized or not self.collection:
            return False

        try:
            doc_id = hashlib.sha256(
                f"{content}{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            meta = {
                "type": memory_type,
                "timestamp": datetime.now().isoformat(),
                "conversation_id": conversation_id or "global",
            }
            if metadata:
                meta.update({k: str(v) for k, v in metadata.items()})

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
        """Retrieve relevant memories for a query."""
        self._init()
        if not self._initialized or not self.collection:
            return []

        try:
            count = self.collection.count()
            if count == 0:
                return []

            n = min(n_results, count)
            embedding = self._embed(query)
            where = {"type": memory_type} if memory_type else None

            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=n,
                where=where,
            )

            memories = []
            for i, doc in enumerate(results["documents"][0]):
                memories.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                })
            return memories
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
        """
        memories = self.retrieve(query, n_results=6)
        if not memories:
            return ""

        lines = ["[NEXUS MEMORY — relevant context from past sessions:]"]
        for m in memories:
            ts = m["metadata"].get("timestamp", "")[:10]
            mtype = m["metadata"].get("type", "memory")
            lines.append(f"• [{ts}] ({mtype}) {m['content']}")

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
