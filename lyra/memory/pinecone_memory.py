"""
Lyra AI Platform — Pinecone Vector Memory Backend
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Pinecone gives Lyra unlimited memory scale — millions of facts vs
ChromaDB's local storage limits. Set PINECONE_API_KEY env var to enable.
"""
import logging
import os
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
INDEX_NAME = "lyra-memory"
EMBED_DIM = 384

# Base importance scores by memory type (mirrors vector_memory.py)
IMPORTANCE_BY_TYPE: Dict[str, float] = {
    "reasoning_template": 9.0,
    "synthesized_wisdom": 10.0,
    "knowledge_gap": 8.0,
    "user_fact": 7.0,
    "learned_knowledge": 5.0,
    "learned_news": 4.0,
    "conversation_summary": 3.0,
    "conversation": 2.0,
}


class PineconeMemory:
    """
    Pinecone-backed vector memory for Lyra.

    Provides the same interface as NexusMemory (ChromaDB) so either backend
    can be used interchangeably.  Uses Pinecone namespaces to partition
    documents by memory_type, enabling efficient filtered retrieval without
    metadata post-filtering.

    Lazy-initialised: the Pinecone client is only created when the first
    operation is attempted AND PINECONE_API_KEY is set.
    """

    def __init__(self):
        self._pc = None          # Pinecone client
        self._index = None       # Pinecone Index handle
        self.embedder = None     # SentenceTransformer model
        self._initialized = False
        self._available = False

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _init(self) -> None:
        """Lazy-init: connect to Pinecone and ensure the index exists."""
        if self._initialized:
            return

        api_key = os.getenv("PINECONE_API_KEY", PINECONE_API_KEY)
        if not api_key:
            logger.debug(
                "PINECONE_API_KEY not set — Pinecone memory disabled. "
                "Set the env var to enable cloud-scale vector storage."
            )
            self._initialized = True  # don't retry
            self._available = False
            return

        try:
            from pinecone import Pinecone, ServerlessSpec

            self._pc = Pinecone(api_key=api_key)

            # Create the index if it doesn't exist yet
            existing = [idx.name for idx in self._pc.list_indexes()]
            if INDEX_NAME not in existing:
                logger.info(f"Creating Pinecone index '{INDEX_NAME}' (dim={EMBED_DIM}, metric=cosine) …")
                self._pc.create_index(
                    name=INDEX_NAME,
                    dimension=EMBED_DIM,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                )
                # Wait until the index is ready
                import time
                for _ in range(30):
                    info = self._pc.describe_index(INDEX_NAME)
                    if info.status.get("ready", False):
                        break
                    time.sleep(2)

            self._index = self._pc.Index(INDEX_NAME)
            self._available = True
            self._initialized = True

            stats = self._index.describe_index_stats()
            total = stats.get("total_vector_count", 0)
            logger.info(
                f"Pinecone memory initialised — index='{INDEX_NAME}', vectors={total:,}"
            )

        except ImportError:
            logger.warning(
                "pinecone package not installed. "
                "Run: pip install pinecone  to enable cloud-scale memory."
            )
            self._initialized = True
            self._available = False
        except Exception as exc:
            logger.error(f"Pinecone init failed: {exc}")
            self._initialized = True
            self._available = False

    def _embed(self, text: str) -> List[float]:
        """Embed text with all-MiniLM-L6-v2 (384-dim)."""
        try:
            from sentence_transformers import SentenceTransformer
            if self.embedder is None:
                self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            return self.embedder.encode(text, normalize_embeddings=True).tolist()
        except ImportError:
            # Deterministic fallback: hash-based pseudo-embedding
            import hashlib
            h = hashlib.sha256(text.encode()).hexdigest()
            return [int(h[i: i + 2], 16) / 255.0 for i in range(0, EMBED_DIM * 2, 2)][:EMBED_DIM]

    # ─── Public interface ─────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if Pinecone is configured and reachable."""
        self._init()
        return self._available

    def store(
        self,
        content: str,
        memory_type: str = "conversation",
        metadata: Dict[str, Any] = None,
    ) -> bool:
        """
        Embed *content* and upsert it into Pinecone.

        The vector is stored in the namespace matching *memory_type*, which
        makes namespace-scoped queries fast without metadata filters.

        Returns True on success, False on any failure.
        """
        self._init()
        if not self._available or self._index is None:
            return False

        try:
            base_importance = IMPORTANCE_BY_TYPE.get(memory_type, 5.0)
            if metadata and "importance" in metadata:
                try:
                    base_importance = float(metadata["importance"])
                except (ValueError, TypeError):
                    pass

            doc_id = str(uuid.uuid4())
            ts = datetime.now().isoformat()

            # Pinecone metadata values must be str / int / float / bool / list[str]
            meta: Dict[str, Any] = {
                "content": content[:3_000],   # Pinecone metadata cap is ~40 KB per vector
                "memory_type": memory_type,
                "timestamp": ts,
                "importance": round(base_importance, 2),
            }
            if metadata:
                for k, v in metadata.items():
                    if k == "importance":
                        continue  # already handled above
                    # Coerce everything to a Pinecone-safe scalar
                    if isinstance(v, (str, int, float, bool)):
                        meta[k] = v
                    else:
                        meta[k] = str(v)

            embedding = self._embed(content)
            self._index.upsert(
                vectors=[(doc_id, embedding, meta)],
                namespace=memory_type,
            )
            return True

        except Exception as exc:
            logger.error(f"Pinecone store failed: {exc}")
            return False

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Embed *query* and return the *n_results* most similar memories.

        If *memory_type* is given, search only that namespace (fast).
        Otherwise query across all namespaces by issuing one query per known
        type and merging/re-ranking results.

        Returned dicts match the NexusMemory format:
          {content, metadata, distance, similarity, importance, composite_score}
        """
        self._init()
        if not self._available or self._index is None:
            return []

        try:
            embedding = self._embed(query)
            fetch_n = min(n_results * 3, 100)   # over-fetch for re-ranking

            raw_matches: List[Dict[str, Any]] = []

            if memory_type:
                # Single-namespace query
                res = self._index.query(
                    vector=embedding,
                    top_k=fetch_n,
                    namespace=memory_type,
                    include_metadata=True,
                )
                raw_matches.extend(res.get("matches", []))
            else:
                # Fan out across all known namespaces
                for ns in IMPORTANCE_BY_TYPE:
                    try:
                        res = self._index.query(
                            vector=embedding,
                            top_k=max(3, n_results),
                            namespace=ns,
                            include_metadata=True,
                        )
                        raw_matches.extend(res.get("matches", []))
                    except Exception:
                        pass  # empty namespace — skip

            memories: List[Dict[str, Any]] = []
            for match in raw_matches:
                meta = match.get("metadata") or {}
                # Pinecone score is cosine similarity (0-1, higher = better)
                score = float(match.get("score", 0.0))
                distance = max(0.0, 1.0 - score)  # convert to distance for compat
                importance = float(meta.get("importance", 5.0))
                composite = (score * 0.6) + ((importance / 10.0) * 0.4)

                memories.append({
                    "content": meta.get("content", ""),
                    "metadata": meta,
                    "distance": distance,
                    "similarity": score,
                    "importance": importance,
                    "composite_score": composite,
                })

            # Re-rank by composite score, return top n
            memories.sort(key=lambda x: x["composite_score"], reverse=True)
            # Deduplicate by content (fan-out may return same vector from diff namespaces)
            seen: set = set()
            deduped: List[Dict[str, Any]] = []
            for m in memories:
                key = m["content"][:120]
                if key not in seen:
                    seen.add(key)
                    deduped.append(m)

            return deduped[:n_results]

        except Exception as exc:
            logger.error(f"Pinecone retrieve failed: {exc}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics dict compatible with NexusMemory.get_stats()."""
        self._init()
        if not self._available or self._index is None:
            return {
                "enabled": False,
                "count": 0,
                "index_name": INDEX_NAME,
            }
        try:
            stats = self._index.describe_index_stats()
            total = stats.get("total_vector_count", 0)
            namespaces = stats.get("namespaces", {})
            return {
                "enabled": True,
                "count": total,
                "index_name": INDEX_NAME,
                "namespaces": {
                    ns: info.get("vector_count", 0)
                    for ns, info in namespaces.items()
                },
                "dimension": EMBED_DIM,
            }
        except Exception as exc:
            logger.error(f"Pinecone get_stats failed: {exc}")
            return {"enabled": self._available, "count": 0, "index_name": INDEX_NAME}

    def clear(self) -> bool:
        """
        Delete all vectors from every namespace in the index.

        This deletes all data but keeps the index itself.
        Returns True on success.
        """
        self._init()
        if not self._available or self._index is None:
            return False
        try:
            for ns in list(IMPORTANCE_BY_TYPE.keys()):
                try:
                    self._index.delete(delete_all=True, namespace=ns)
                except Exception:
                    pass  # namespace may not exist yet
            logger.info(f"Pinecone index '{INDEX_NAME}' cleared.")
            return True
        except Exception as exc:
            logger.error(f"Pinecone clear failed: {exc}")
            return False

    # ─── Convenience wrappers (parity with NexusMemory) ──────────────────────

    def store_user_fact(self, fact: str) -> bool:
        """Store a fact about the user."""
        return self.store(fact, memory_type="user_fact")

    def store_conversation_summary(self, summary: str, conv_id: str) -> bool:
        """Store a summary of a completed conversation."""
        return self.store(
            summary,
            memory_type="conversation_summary",
            metadata={"conversation_id": conv_id},
        )

    def get_context_for_prompt(self, query: str) -> str:
        """
        Retrieve relevant memories and format them as a prompt context block.
        Mirrors NexusMemory.get_context_for_prompt().
        """
        memories = self.retrieve(query, n_results=8)
        if not memories:
            return ""

        lines = ["[Lyra MEMORY (Pinecone) — relevant context from past sessions:]"]
        for m in memories:
            ts = m["metadata"].get("timestamp", "")[:10]
            mtype = m["metadata"].get("memory_type", "memory")
            importance = m.get("importance", 5.0)

            if importance >= 9:
                prefix = "★"
            elif importance >= 7:
                prefix = "•"
            else:
                prefix = "·"

            lines.append(f"{prefix} [{ts}] ({mtype}) {m['content'][:350]}")

        return "\n".join(lines)


# Global singleton — only active when PINECONE_API_KEY is set
pinecone_memory = PineconeMemory()
