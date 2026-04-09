"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          LYRA — Super-Intelligence RAG Pipeline                              ║
║                                                                              ║
║  Architecture:                                                               ║
║    FineWeb-v2 / StarCoder2 / Your Files                                      ║
║           ↓                                                                  ║
║    BAAI/bge-m3  (1024-dim dense embeddings)                                  ║
║    BM25         (sparse keyword embeddings)                                  ║
║           ↓                                                                  ║
║    Pinecone Serverless  (hybrid dense+sparse index)                          ║
║           ↓  query                                                           ║
║    Hybrid Search  →  Cross-Encoder Re-ranker                                 ║
║           ↓                                                                  ║
║    Chain-of-Thought prompt  →  Claude claude-sonnet-4-6                          ║
║                                                                              ║
║  Usage:                                                                      ║
║    from lyra.intelligence.super_pipeline import SuperPipeline                ║
║    pipe = SuperPipeline()                                                    ║
║    pipe.ingest_fineweb(max_docs=50_000)                                      ║
║    pipe.ingest_starcoder(max_docs=20_000)                                    ║
║    pipe.ingest_file("my_notes.pdf")          # upload your own files        ║
║    answer = pipe.query("How does attention mechanism work?")                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

Install dependencies:
    pip install pinecone pinecone-text sentence-transformers datasets \
                transformers accelerate anthropic langchain-anthropic \
                torch trl wandb xformers --prefer-binary
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
INDEX_NAME       = "lyra-super-intelligence"
EMBEDDING_MODEL  = "BAAI/bge-m3"           # 1024-dim, multilingual, SOTA 2026
RERANKER_MODEL   = "cross-encoder/ms-marco-MiniLM-L-6-v2"
EMBED_DIM        = 1024
BATCH_SIZE       = 150                      # Pinecone upsert batch
CHUNK_WORDS      = 400                      # words per chunk
CHUNK_OVERLAP    = 50                       # overlap between chunks
TOP_K_RETRIEVE   = 20                       # candidates before re-ranking
TOP_K_FINAL      = 5                        # results after re-ranking


# ── Retry decorator ───────────────────────────────────────────────────────────

def with_retry(max_retries: int = 5, base_delay: float = 1.0):
    """Exponential-backoff retry for Anthropic + Pinecone overload errors."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    err = str(e).lower()
                    retryable = any(x in err for x in [
                        "overloaded", "rate_limit", "529", "503",
                        "too_many_requests", "internal_server"
                    ])
                    if retryable and attempt < max_retries - 1:
                        logger.warning(f"[Retry {attempt+1}/{max_retries}] {e} — waiting {delay:.1f}s")
                        time.sleep(delay)
                        delay = min(delay * 2, 60)   # cap at 60s
                    else:
                        raise
            raise RuntimeError("Max retries exceeded")
        return wrapper
    return decorator


# ── Text chunker ──────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping word-level chunks."""
    words = text.split()
    chunks = []
    step = chunk_words - overlap
    for i in range(0, max(1, len(words) - overlap), step):
        chunk = " ".join(words[i : i + chunk_words])
        if chunk.strip():
            chunks.append(chunk.strip())
        if i + chunk_words >= len(words):
            break
    return chunks or [text[:2000]]   # fallback: first 2000 chars


# ── Embedding engine (BAAI/bge-m3) ───────────────────────────────────────────

class EmbeddingEngine:
    """
    BAAI/bge-m3 — 1024-dim multilingual dense embeddings.
    Best open-source embedding model as of 2026.
    """
    def __init__(self):
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
            self._model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Embedding model ready.")

    def embed(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """Embed a list of texts. Returns list of 1024-dim float vectors."""
        self._load()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,   # cosine similarity via dot product
            show_progress_bar=len(texts) > 100,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query string (prepends BGE instruction prefix)."""
        self._load()
        # BGE-M3 query instruction prefix for retrieval tasks
        instructed = f"Represent this sentence for searching relevant passages: {query}"
        return self.embed([instructed])[0]


# ── Sparse encoder (BM25) ─────────────────────────────────────────────────────

class SparseEncoder:
    """BM25 sparse encoder for keyword-based retrieval (hybrid search)."""

    def __init__(self, corpus: Optional[List[str]] = None):
        self._encoder = None
        if corpus:
            self.fit(corpus)

    def fit(self, corpus: List[str]):
        from pinecone_text.sparse import BM25Encoder
        logger.info(f"Fitting BM25 on {len(corpus):,} documents...")
        self._encoder = BM25Encoder()
        self._encoder.fit(corpus)
        logger.info("BM25 ready.")

    def encode_documents(self, texts: List[str]) -> List[Dict]:
        if self._encoder is None:
            self.fit(texts)
        return [self._encoder.encode_documents(t) for t in texts]

    def encode_query(self, query: str) -> Dict:
        if self._encoder is None:
            return {"indices": [], "values": []}
        return self._encoder.encode_queries(query)


# ── Pinecone vector store ─────────────────────────────────────────────────────

class PineconeStore:
    """
    Pinecone Serverless index with hybrid search (dense + sparse).
    Automatically creates the index on first use.
    """

    def __init__(self, api_key: Optional[str] = None, cloud: str = "aws", region: str = "us-east-1"):
        self.api_key = api_key or os.getenv("PINECONE_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "PINECONE_API_KEY not set. "
                "Get your key at https://app.pinecone.io — sign in with GitHub."
            )
        self.cloud  = cloud
        self.region = region
        self._index = None
        self._pc    = None

    def _connect(self):
        if self._index is not None:
            return
        from pinecone import Pinecone, ServerlessSpec
        self._pc = Pinecone(api_key=self.api_key)

        existing = [i.name for i in self._pc.list_indexes()]
        if INDEX_NAME not in existing:
            logger.info(f"Creating Pinecone index '{INDEX_NAME}' ({EMBED_DIM}-dim, cosine, hybrid)...")
            self._pc.create_index(
                name=INDEX_NAME,
                dimension=EMBED_DIM,
                metric="dotproduct",      # dotproduct required for hybrid search
                spec=ServerlessSpec(cloud=self.cloud, region=self.region),
            )
            # Wait for index to be ready
            for _ in range(30):
                status = self._pc.describe_index(INDEX_NAME).status
                if status.get("ready"):
                    break
                time.sleep(2)
            logger.info("Index ready.")
        else:
            logger.info(f"Connected to existing index '{INDEX_NAME}'.")

        self._index = self._pc.Index(INDEX_NAME)

    @with_retry(max_retries=5, base_delay=1.0)
    def upsert_batch(
        self,
        ids:             List[str],
        dense_vecs:      List[List[float]],
        sparse_vecs:     Optional[List[Dict]],
        metadata:        List[Dict],
    ):
        """Upsert one batch of vectors into Pinecone."""
        self._connect()
        vectors = []
        for i, (vid, dv, meta) in enumerate(zip(ids, dense_vecs, metadata)):
            v: Dict[str, Any] = {"id": vid, "values": dv, "metadata": meta}
            if sparse_vecs and i < len(sparse_vecs):
                v["sparse_values"] = sparse_vecs[i]
            vectors.append(v)
        self._index.upsert(vectors=vectors)

    @with_retry(max_retries=5, base_delay=1.0)
    def hybrid_search(
        self,
        dense_vec:    List[float],
        sparse_vec:   Optional[Dict],
        top_k:        int = TOP_K_RETRIEVE,
        alpha:        float = 0.7,        # 0 = pure sparse, 1 = pure dense
        namespace:    str = "",
    ) -> List[Dict]:
        """
        Hybrid search: alpha * dense + (1-alpha) * sparse.
        alpha=0.7 = mostly semantic, 30% keyword boost.
        """
        self._connect()

        # Scale vectors by alpha
        scaled_dense  = [v * alpha for v in dense_vec]
        scaled_sparse = None
        if sparse_vec and sparse_vec.get("indices"):
            sparse_scale = 1.0 - alpha
            scaled_sparse = {
                "indices": sparse_vec["indices"],
                "values":  [v * sparse_scale for v in sparse_vec["values"]],
            }

        kwargs: Dict[str, Any] = {
            "vector":          scaled_dense,
            "top_k":           top_k,
            "include_metadata": True,
        }
        if scaled_sparse:
            kwargs["sparse_vector"] = scaled_sparse
        if namespace:
            kwargs["namespace"] = namespace

        result = self._index.query(**kwargs)
        return result.get("matches", [])

    def stats(self) -> Dict:
        self._connect()
        return self._index.describe_index_stats()


# ── Cross-encoder re-ranker ───────────────────────────────────────────────────

class ReRanker:
    """
    Cross-encoder ms-marco-MiniLM-L-6-v2.
    Re-scores query+passage pairs for precision — much more accurate than
    bi-encoder cosine similarity alone.
    """
    def __init__(self):
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading re-ranker: {RERANKER_MODEL}")
            self._model = CrossEncoder(RERANKER_MODEL, max_length=512)
            logger.info("Re-ranker ready.")

    def rerank(self, query: str, candidates: List[Dict], top_k: int = TOP_K_FINAL) -> List[Dict]:
        """
        Score each candidate against the query, return top_k sorted by score.
        Each candidate must have metadata['text'].
        """
        if not candidates:
            return []
        self._load()
        pairs = [(query, c["metadata"].get("text", "")) for c in candidates]
        scores = self._model.predict(pairs)
        ranked = sorted(
            zip(scores, candidates),
            key=lambda x: x[0],
            reverse=True,
        )
        results = []
        for score, match in ranked[:top_k]:
            match["rerank_score"] = float(score)
            results.append(match)
        return results


# ── Claude reasoning layer ────────────────────────────────────────────────────

class ClaudeReasoner:
    """
    Anthropic Claude claude-sonnet-4-6 with Chain-of-Thought prompting.
    Receives re-ranked context and returns a reasoned answer.
    """
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model   = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _build_cot_prompt(self, query: str, context_docs: List[Dict]) -> str:
        """
        Build a Chain-of-Thought prompt in Anthropic style.
        Structures the context as numbered sources, then asks for step-by-step reasoning.
        """
        sources = ""
        for i, doc in enumerate(context_docs, 1):
            meta   = doc.get("metadata", {})
            source = meta.get("source", "Unknown")
            text   = meta.get("text", "")[:800]
            score  = doc.get("rerank_score", doc.get("score", 0))
            sources += f"\n[{i}] Source: {source} (relevance: {score:.3f})\n{text}\n"

        return f"""You are Lyra, a super-intelligent AI with access to a massive knowledge base.
Answer the question using the provided sources. Think step by step.

<sources>
{sources}
</sources>

<question>
{query}
</question>

<instructions>
1. First, identify which sources are most relevant to the question.
2. Reason through the answer step by step — show your thinking.
3. Synthesize a comprehensive, accurate answer.
4. Cite source numbers [1], [2] etc. where relevant.
5. If sources are insufficient, say so clearly and answer from your training knowledge.
</instructions>

Let me think through this carefully:"""

    @with_retry(max_retries=5, base_delay=1.0)
    def reason(self, query: str, context_docs: List[Dict], max_tokens: int = 2048) -> str:
        """Call Claude with re-ranked context. Returns the full Chain-of-Thought answer."""
        if not self.api_key:
            return "[ANTHROPIC_API_KEY not set — reasoning layer disabled. Set env var to enable.]"

        client = self._get_client()
        prompt = self._build_cot_prompt(query, context_docs)

        message = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text


# ── Main pipeline ─────────────────────────────────────────────────────────────

class SuperPipeline:
    """
    Full RAG pipeline:
      ingest → embed → upsert → hybrid search → rerank → Claude CoT answer
    """

    def __init__(
        self,
        pinecone_api_key:  Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        cloud:             str = "aws",
        region:            str = "us-east-1",
    ):
        self.embedder = EmbeddingEngine()
        self.sparse   = SparseEncoder()
        self.store    = PineconeStore(api_key=pinecone_api_key, cloud=cloud, region=region)
        self.reranker = ReRanker()
        self.claude   = ClaudeReasoner(api_key=anthropic_api_key)
        logger.info("SuperPipeline initialised.")

    # ── Ingestion helpers ──────────────────────────────────────────────────────

    def _ingest_chunks(self, chunks: List[str], source: str, namespace: str = ""):
        """Embed + upsert a list of text chunks into Pinecone."""
        if not chunks:
            return

        # Fit BM25 on this batch (incremental)
        self.sparse.fit(chunks)

        dense_vecs  = self.embedder.embed(chunks)
        sparse_vecs = self.sparse.encode_documents(chunks)
        now_iso     = datetime.now(timezone.utc).isoformat()

        # Batch upsert
        for i in range(0, len(chunks), BATCH_SIZE):
            batch_chunks  = chunks[i : i + BATCH_SIZE]
            batch_dense   = dense_vecs[i : i + BATCH_SIZE]
            batch_sparse  = sparse_vecs[i : i + BATCH_SIZE]
            batch_ids     = [
                hashlib.md5(c.encode()).hexdigest()[:16] + "_" + str(uuid.uuid4())[:8]
                for c in batch_chunks
            ]
            batch_meta = [
                {
                    "text":      c[:1000],      # Pinecone metadata limit
                    "source":    source,
                    "timestamp": now_iso,
                    "word_count": len(c.split()),
                }
                for c in batch_chunks
            ]
            self.store.upsert_batch(batch_ids, batch_dense, batch_sparse, batch_meta)
            logger.info(f"  Upserted batch {i//BATCH_SIZE + 1} ({len(batch_chunks)} chunks) from '{source}'")

    # ── Dataset ingestion ──────────────────────────────────────────────────────

    def ingest_fineweb(self, max_docs: int = 50_000, lang: str = "en"):
        """
        Stream FineWeb-v2 (15T+ token web text corpus).
        Uses streaming=True — never loads the full dataset into RAM.
        """
        logger.info(f"Streaming FineWeb-v2 ({max_docs:,} docs, lang={lang})...")
        try:
            from datasets import load_dataset
            ds = load_dataset(
                "HuggingFaceFW/fineweb-v2",
                name=f"CC-MAIN-2024-10",   # most recent crawl snapshot
                split="train",
                streaming=True,
                trust_remote_code=True,
            )
            buffer: List[str] = []
            count = 0
            for row in ds:
                text = row.get("text", "").strip()
                if not text or len(text.split()) < 50:
                    continue
                for chunk in chunk_text(text):
                    buffer.append(chunk)
                count += 1
                if len(buffer) >= BATCH_SIZE * 4:
                    self._ingest_chunks(buffer, source="fineweb-v2")
                    buffer = []
                if count >= max_docs:
                    break
            if buffer:
                self._ingest_chunks(buffer, source="fineweb-v2")
            logger.info(f"FineWeb-v2 ingestion complete: {count:,} documents processed.")
        except Exception as e:
            logger.error(f"FineWeb ingestion error: {e}")
            raise

    def ingest_starcoder(self, max_docs: int = 20_000, languages: Optional[List[str]] = None):
        """
        Stream StarCoder2 (The Stack v2 — all programming languages).
        Default languages: Python, JavaScript, TypeScript, Rust, Go.
        """
        langs = languages or ["python", "javascript", "typescript", "rust", "go"]
        logger.info(f"Streaming StarCoder2 ({max_docs:,} files, langs={langs})...")
        try:
            from datasets import load_dataset
            count = 0
            for lang in langs:
                if count >= max_docs:
                    break
                try:
                    ds = load_dataset(
                        "bigcode/the-stack-v2",
                        data_dir=f"data/{lang}",
                        split="train",
                        streaming=True,
                        trust_remote_code=True,
                    )
                    buffer: List[str] = []
                    per_lang = max_docs // len(langs)
                    lang_count = 0
                    for row in ds:
                        content = row.get("content", "").strip()
                        if not content or len(content) < 100:
                            continue
                        for chunk in chunk_text(content, chunk_words=300):
                            buffer.append(chunk)
                        lang_count += 1
                        count += 1
                        if len(buffer) >= BATCH_SIZE * 4:
                            self._ingest_chunks(buffer, source=f"starcoder2-{lang}")
                            buffer = []
                        if lang_count >= per_lang:
                            break
                    if buffer:
                        self._ingest_chunks(buffer, source=f"starcoder2-{lang}")
                    logger.info(f"  {lang}: {lang_count:,} files ingested")
                except Exception as e:
                    logger.warning(f"  Skipping {lang}: {e}")
            logger.info(f"StarCoder2 ingestion complete: {count:,} files total.")
        except Exception as e:
            logger.error(f"StarCoder ingestion error: {e}")
            raise

    def ingest_dataset(
        self,
        dataset_name: str,
        text_column:  str = "text",
        split:        str = "train",
        max_docs:     int = 10_000,
        config:       Optional[str] = None,
    ):
        """
        Generic HuggingFace dataset ingestion.
        Example: pipe.ingest_dataset("wikipedia", text_column="text", config="20231101.en")
        """
        logger.info(f"Streaming {dataset_name} (max {max_docs:,} docs)...")
        from datasets import load_dataset
        kwargs: Dict[str, Any] = {"split": split, "streaming": True, "trust_remote_code": True}
        if config:
            kwargs["name"] = config
        ds = load_dataset(dataset_name, **kwargs)
        buffer: List[str] = []
        count = 0
        for row in ds:
            text = str(row.get(text_column, "")).strip()
            if not text or len(text.split()) < 30:
                continue
            for chunk in chunk_text(text):
                buffer.append(chunk)
            count += 1
            if len(buffer) >= BATCH_SIZE * 4:
                self._ingest_chunks(buffer, source=dataset_name)
                buffer = []
            if count >= max_docs:
                break
        if buffer:
            self._ingest_chunks(buffer, source=dataset_name)
        logger.info(f"{dataset_name} ingestion complete: {count:,} docs.")

    def ingest_file(self, path: str):
        """
        Ingest a local file — PDF, TXT, JSONL, or Markdown.
        This is the easy upload path for your own notes, docs, and data.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        logger.info(f"Ingesting local file: {p.name}")
        ext = p.suffix.lower()

        if ext == ".pdf":
            text = self._read_pdf(p)
        elif ext in (".txt", ".md"):
            text = p.read_text(encoding="utf-8", errors="ignore")
        elif ext == ".jsonl":
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            import json
            texts = []
            for line in lines:
                try:
                    obj = json.loads(line)
                    texts.append(str(obj.get("text", obj.get("content", str(obj)))))
                except Exception:
                    texts.append(line)
            text = "\n\n".join(texts)
        else:
            text = p.read_text(encoding="utf-8", errors="ignore")

        chunks = chunk_text(text)
        logger.info(f"  Split into {len(chunks):,} chunks")
        self._ingest_chunks(chunks, source=p.name)
        logger.info(f"File '{p.name}' ingested: {len(chunks):,} chunks stored.")

    def ingest_text(self, text: str, source: str = "manual"):
        """Ingest a raw string directly (useful for programmatic ingestion)."""
        chunks = chunk_text(text)
        self._ingest_chunks(chunks, source=source)

    def _read_pdf(self, path: Path) -> str:
        try:
            import fitz  # pymupdf
            doc = fitz.open(str(path))
            return "\n".join(page.get_text() for page in doc)
        except ImportError:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                return "\n".join(p.extract_text() or "" for p in reader.pages)
            except ImportError:
                raise ImportError("Install pymupdf or pypdf to read PDFs: pip install pymupdf")

    # ── Query ──────────────────────────────────────────────────────────────────

    def query(
        self,
        question:      str,
        top_k:         int = TOP_K_FINAL,
        alpha:         float = 0.7,
        use_claude:    bool = True,
        max_tokens:    int = 2048,
    ) -> Dict[str, Any]:
        """
        Full pipeline query:
          1. Embed question (dense + sparse)
          2. Hybrid search Pinecone
          3. Cross-encoder re-rank
          4. Claude Chain-of-Thought reasoning

        Returns dict with 'answer', 'sources', 'chunks_retrieved'.
        """
        logger.info(f"Query: {question[:80]}...")

        # 1. Encode
        dense_vec  = self.embedder.embed_query(question)
        sparse_vec = self.sparse.encode_query(question)

        # 2. Hybrid search
        candidates = self.store.hybrid_search(
            dense_vec=dense_vec,
            sparse_vec=sparse_vec,
            top_k=TOP_K_RETRIEVE,
            alpha=alpha,
        )
        logger.info(f"  Retrieved {len(candidates)} candidates from Pinecone")

        # 3. Re-rank
        ranked = self.reranker.rerank(question, candidates, top_k=top_k)
        logger.info(f"  Re-ranked to top {len(ranked)} results")

        # 4. Claude reasoning
        if use_claude and ranked:
            answer = self.claude.reason(question, ranked, max_tokens=max_tokens)
        elif ranked:
            # Fallback: just return the top chunk text
            answer = ranked[0]["metadata"].get("text", "No answer found.")
        else:
            answer = "No relevant information found in the knowledge base."

        return {
            "answer":           answer,
            "chunks_retrieved": len(candidates),
            "sources":          [
                {
                    "source":       r["metadata"].get("source", "?"),
                    "text":         r["metadata"].get("text", "")[:300],
                    "rerank_score": round(r.get("rerank_score", 0), 4),
                    "vector_score": round(r.get("score", 0), 4),
                }
                for r in ranked
            ],
        }

    def stats(self) -> Dict:
        """Return Pinecone index stats."""
        return self.store.stats()
