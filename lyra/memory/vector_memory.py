"""Lyra Vector Memory with importance scoring"""
import json, logging, hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
logger = logging.getLogger(__name__)
MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
IMPORTANCE_BY_TYPE = {"reasoning_template": 9.0, "synthesized_wisdom": 10.0, "knowledge_gap": 8.0, "user_fact": 7.0, "learned_knowledge": 5.0, "conversation": 2.0}
class NexusMemory:
    def __init__(self):
        self.client = None; self.collection = None; self._fallback: List[Dict] = []; self._initialized = False
    def _init(self):
        if self._initialized: return
        self._initialized = True
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=str(MEMORY_DIR))
            self.collection = self.client.get_or_create_collection("lyra_memory", metadata={"hnsw:space": "cosine"})
        except Exception as e:
            logger.info(f"ChromaDB unavailable, using fallback: {e}")
    def store(self, content: str, memory_type: str = "conversation", metadata: Dict = None) -> bool:
        self._init()
        try:
            if self.collection:
                import uuid
                mid = str(uuid.uuid4())
                meta = metadata or {}
                meta.update({"type": memory_type, "timestamp": datetime.now().isoformat(), "importance": IMPORTANCE_BY_TYPE.get(memory_type, 5.0)})
                self.collection.add(documents=[content], metadatas=[meta], ids=[mid])
            else:
                self._fallback.append({"content": content, "type": memory_type, "metadata": metadata or {}})
            return True
        except Exception as e:
            logger.debug(f"Memory store error: {e}"); return False
    def search(self, query: str, n_results: int = 5, memory_type: str = None) -> List[Dict]:
        self._init()
        try:
            if self.collection and self.collection.count() > 0:
                where = {"type": memory_type} if memory_type else None
                results = self.collection.query(query_texts=[query], n_results=min(n_results, self.collection.count()), where=where)
                docs = results["documents"][0] if results["documents"] else []
                metas = results["metadatas"][0] if results["metadatas"] else []
                return [{"content": d, **m} for d, m in zip(docs, metas)]
        except Exception as e:
            logger.debug(f"Memory search error: {e}")
        return [m for m in self._fallback if query.lower() in m["content"].lower()][:n_results]
    def get_context_for_prompt(self, query: str, max_tokens: int = 800) -> str:
        memories = self.search(query, n_results=8)
        if not memories: return ""
        lines = []
        total = 0
        for m in memories:
            line = f"[{m.get('type','memory')}] {m.get('content','')[:200]}"
            total += len(line)
            if total > max_tokens * 4: break
            lines.append(line)
        return "\n".join(lines)
    def get_stats(self) -> Dict:
        self._init()
        try:
            if self.collection: return {"enabled": True, "count": self.collection.count()}
        except: pass
        return {"enabled": False, "count": len(self._fallback)}
memory = NexusMemory()
