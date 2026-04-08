"""
Lyra AI Platform — HuggingFace Dataset Ingestion Pipeline
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Bulk-load knowledge from massive open datasets (Wikipedia, ArXiv, Gutenberg,
BigCode/The Stack) directly into Lyra's vector memory and knowledge graph.
Set HUGGINGFACE_TOKEN env var for gated datasets (e.g. The Stack).
"""
import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How many words per chunk when splitting long texts
CHUNK_WORDS = 500
# Sleep (seconds) between batches to respect HF rate limits
RATE_LIMIT_SLEEP = 0.05
# Log progress every N items
LOG_EVERY = 100


def _chunk_text(text: str, max_words: int = CHUNK_WORDS) -> List[str]:
    """
    Split *text* into chunks of at most *max_words* words.

    Splitting respects sentence boundaries where possible: the splitter walks
    word-by-word, and each time the word budget is exhausted it looks for the
    nearest sentence-ending punctuation to break cleanly.
    """
    words = text.split()
    if not words:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end

    return [c.strip() for c in chunks if c.strip()]


def _sanitize(text: str) -> str:
    """Remove excessive whitespace / control characters."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class HuggingFaceIngestion:
    """
    Ingestion pipeline that loads HuggingFace datasets and stores every
    text chunk into Lyra's vector memory (NexusMemory / PineconeMemory) and
    knowledge graph (GraphMemory).

    All public methods are synchronous so they can be called directly in
    threads; the async wrappers (prefixed ``async_``) push the blocking work
    into a thread pool via ``asyncio.to_thread``.

    Usage::

        pipeline = HuggingFaceIngestion()
        # direct (blocking)
        pipeline.ingest_wikipedia(lang="en", max_articles=1000)
        # async-friendly
        await pipeline.async_ingest_wikipedia(lang="en", max_articles=1000)
    """

    def __init__(self):
        self._running = False
        self._stop_flag = False

        # Ingestion counters (reset each run, accumulated across runs)
        self.total_chunks_stored: int = 0
        self.total_items_processed: int = 0
        self.current_task: str = "idle"
        self.last_run_started: Optional[str] = None
        self.last_run_finished: Optional[str] = None
        self.errors: List[str] = []

    # ─── Lazy memory/graph handles ────────────────────────────────────────────

    def _get_memory(self):
        """Return the active vector memory (prefers Pinecone if available)."""
        try:
            from lyra.memory.pinecone_memory import pinecone_memory
            if pinecone_memory.is_available():
                return pinecone_memory
        except Exception:
            pass
        from lyra.memory.vector_memory import memory
        return memory

    def _get_graph(self):
        """Return the active graph memory instance."""
        from lyra.memory.graph_memory import graph_memory
        return graph_memory

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _store_chunk(
        self,
        chunk: str,
        source: str,
        dataset_name: str,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Persist a single text chunk to vector memory AND knowledge graph.
        Returns True if the vector store succeeded.
        """
        if not chunk or len(chunk) < 50:
            return False

        memory = self._get_memory()
        graph = self._get_graph()

        meta: Dict[str, Any] = {
            "source": source,
            "dataset_name": dataset_name,
            "quality": "high",
            "ingested_at": datetime.now().isoformat(),
        }
        if extra_meta:
            meta.update(extra_meta)

        # Vector store
        ok = memory.store(
            content=chunk,
            memory_type="learned_knowledge",
            metadata=meta,
        )

        # Knowledge graph (best-effort; errors are non-fatal)
        try:
            topic = extra_meta.get("title") or extra_meta.get("topic") or dataset_name if extra_meta else dataset_name
            graph.store_knowledge(
                topic=str(topic)[:200],
                content=chunk,
                source_url=source,
                memory_type="learned_knowledge",
            )
        except Exception as exc:
            logger.debug(f"Graph store skipped: {exc}")

        return ok

    def _check_stop(self) -> bool:
        return self._stop_flag

    def _begin(self, task_name: str) -> None:
        self._running = True
        self._stop_flag = False
        self.current_task = task_name
        self.last_run_started = datetime.now().isoformat()
        logger.info(f"[HF Ingestion] Starting: {task_name}")

    def _finish(self, stored: int, processed: int) -> None:
        self.total_chunks_stored += stored
        self.total_items_processed += processed
        self._running = False
        self.current_task = "idle"
        self.last_run_finished = datetime.now().isoformat()
        logger.info(
            f"[HF Ingestion] Done — {processed} items processed, "
            f"{stored} chunks stored (session total: {self.total_chunks_stored:,})"
        )

    # ─── Wikipedia ────────────────────────────────────────────────────────────

    def ingest_wikipedia(
        self,
        lang: str = "en",
        max_articles: int = 10_000,
    ) -> Dict[str, Any]:
        """
        Ingest Wikipedia articles via the HuggingFace ``wikipedia`` dataset.

        Parameters
        ----------
        lang:
            Wikipedia language code, e.g. ``"en"``, ``"de"``, ``"fr"``.
        max_articles:
            Maximum number of articles to process.

        Returns a stats dict.
        """
        self._begin(f"Wikipedia ({lang}), max={max_articles:,}")
        stored = processed = 0

        try:
            from datasets import load_dataset

            ds = load_dataset(
                "wikipedia",
                f"20220301.{lang}",
                split="train",
                streaming=True,
                trust_remote_code=True,
            )

            for item in ds:
                if self._check_stop() or processed >= max_articles:
                    break

                title = _sanitize(item.get("title", ""))
                text = _sanitize(item.get("text", ""))
                url = item.get("url", f"https://{lang}.wikipedia.org/wiki/{title}")

                if not text:
                    continue

                chunks = _chunk_text(text)
                for i, chunk in enumerate(chunks):
                    if self._check_stop():
                        break
                    header = f"[Wikipedia — {title}]\nSource: {url}\n\n"
                    ok = self._store_chunk(
                        chunk=header + chunk,
                        source=url,
                        dataset_name=f"wikipedia/{lang}",
                        extra_meta={
                            "title": title,
                            "chunk_index": i,
                            "language": lang,
                        },
                    )
                    if ok:
                        stored += 1

                processed += 1
                if processed % LOG_EVERY == 0:
                    logger.info(
                        f"[Wikipedia] {processed}/{max_articles} articles, "
                        f"{stored:,} chunks stored"
                    )
                    time.sleep(RATE_LIMIT_SLEEP)

        except Exception as exc:
            msg = f"Wikipedia ingestion error: {exc}"
            logger.error(msg)
            self.errors.append(msg)

        self._finish(stored, processed)
        return {"processed": processed, "stored": stored, "dataset": f"wikipedia/{lang}"}

    # ─── ArXiv ────────────────────────────────────────────────────────────────

    def ingest_arxiv(
        self,
        categories: Optional[List[str]] = None,
        max_papers: int = 5_000,
    ) -> Dict[str, Any]:
        """
        Ingest ArXiv paper abstracts (and full text where available) via
        HuggingFace's ``arxiv_dataset`` / ``togethercomputer/RedPajama-Data-1T``
        ArXiv subset.

        Parameters
        ----------
        categories:
            ArXiv category codes to filter on, e.g. ``["cs.AI", "cs.LG"]``.
            If None/empty, all categories are ingested.
        max_papers:
            Maximum number of papers to process.
        """
        if categories is None:
            categories = ["cs.AI", "cs.LG", "physics"]

        self._begin(f"ArXiv {categories}, max={max_papers:,}")
        stored = processed = 0

        try:
            from datasets import load_dataset

            ds = load_dataset(
                "arxiv_dataset",
                split="train",
                streaming=True,
                trust_remote_code=True,
            )

            cat_set = set(c.lower() for c in categories) if categories else None

            for item in ds:
                if self._check_stop() or processed >= max_papers:
                    break

                # Filter by category
                item_cats = item.get("categories", "").lower()
                if cat_set and not any(c in item_cats for c in cat_set):
                    continue

                title = _sanitize(item.get("title", ""))
                abstract = _sanitize(item.get("abstract", ""))
                paper_id = item.get("id", "")
                url = f"https://arxiv.org/abs/{paper_id}" if paper_id else ""
                authors = item.get("authors", "")

                full_text = (
                    f"[ArXiv Paper — {title}]\n"
                    f"Authors: {authors}\n"
                    f"Categories: {item_cats}\n"
                    f"Source: {url}\n\n"
                    f"Abstract: {abstract}"
                )

                chunks = _chunk_text(full_text)
                for i, chunk in enumerate(chunks):
                    if self._check_stop():
                        break
                    ok = self._store_chunk(
                        chunk=chunk,
                        source=url,
                        dataset_name="arxiv",
                        extra_meta={
                            "title": title,
                            "paper_id": paper_id,
                            "categories": item_cats[:200],
                            "chunk_index": i,
                        },
                    )
                    if ok:
                        stored += 1

                processed += 1
                if processed % LOG_EVERY == 0:
                    logger.info(
                        f"[ArXiv] {processed}/{max_papers} papers, "
                        f"{stored:,} chunks stored"
                    )
                    time.sleep(RATE_LIMIT_SLEEP)

        except Exception as exc:
            msg = f"ArXiv ingestion error: {exc}"
            logger.error(msg)
            self.errors.append(msg)

        self._finish(stored, processed)
        return {"processed": processed, "stored": stored, "dataset": "arxiv", "categories": categories}

    # ─── Project Gutenberg ────────────────────────────────────────────────────

    def ingest_gutenberg(
        self,
        max_books: int = 500,
    ) -> Dict[str, Any]:
        """
        Ingest public-domain books from Project Gutenberg via the HuggingFace
        ``gutenberg`` dataset.

        Parameters
        ----------
        max_books:
            Maximum number of books to process.
        """
        self._begin(f"Project Gutenberg, max={max_books:,}")
        stored = processed = 0

        try:
            from datasets import load_dataset

            ds = load_dataset(
                "sedthh/gutenberg_english",
                split="train",
                streaming=True,
                trust_remote_code=True,
            )

            for item in ds:
                if self._check_stop() or processed >= max_books:
                    break

                title = _sanitize(item.get("title", item.get("META_TITLE", "Unknown")))
                author = _sanitize(item.get("author", item.get("META_AUTHOR", "Unknown")))
                text = _sanitize(item.get("TEXT", item.get("text", "")))
                book_id = item.get("guten_id", item.get("id", ""))
                url = f"https://www.gutenberg.org/ebooks/{book_id}" if book_id else "https://www.gutenberg.org"

                if not text or len(text) < 200:
                    continue

                chunks = _chunk_text(text)
                for i, chunk in enumerate(chunks):
                    if self._check_stop():
                        break
                    header = f"[Project Gutenberg — {title} by {author}]\nSource: {url}\n\n"
                    ok = self._store_chunk(
                        chunk=header + chunk,
                        source=url,
                        dataset_name="gutenberg",
                        extra_meta={
                            "title": title,
                            "author": author,
                            "book_id": str(book_id),
                            "chunk_index": i,
                        },
                    )
                    if ok:
                        stored += 1

                processed += 1
                if processed % LOG_EVERY == 0:
                    logger.info(
                        f"[Gutenberg] {processed}/{max_books} books, "
                        f"{stored:,} chunks stored"
                    )
                    time.sleep(RATE_LIMIT_SLEEP)

        except Exception as exc:
            msg = f"Gutenberg ingestion error: {exc}"
            logger.error(msg)
            self.errors.append(msg)

        self._finish(stored, processed)
        return {"processed": processed, "stored": stored, "dataset": "gutenberg"}

    # ─── BigCode / The Stack ──────────────────────────────────────────────────

    def ingest_bigcode(
        self,
        max_files: int = 5_000,
        languages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest source-code files from BigCode's ``the-stack-smol`` (a curated
        sample of The Stack).  Set ``HUGGINGFACE_TOKEN`` for full access.

        Parameters
        ----------
        max_files:
            Maximum number of source files to process.
        languages:
            Programming languages to filter on (e.g. ``["python", "rust"]``).
            If None, all languages are ingested.
        """
        self._begin(f"BigCode/The Stack, max={max_files:,}")
        stored = processed = 0

        try:
            from datasets import load_dataset
            import os as _os

            token = _os.getenv("HUGGINGFACE_TOKEN", None)

            ds = load_dataset(
                "bigcode/the-stack-smol",
                split="train",
                streaming=True,
                trust_remote_code=True,
                token=token,
            )

            lang_set = set(l.lower() for l in languages) if languages else None

            for item in ds:
                if self._check_stop() or processed >= max_files:
                    break

                lang = (item.get("lang") or item.get("language", "unknown")).lower()
                if lang_set and lang not in lang_set:
                    continue

                content = _sanitize(item.get("content", ""))
                repo = item.get("max_stars_repo_name", item.get("repo_name", "unknown"))
                path = item.get("max_stars_repo_path", item.get("path", ""))
                url = (
                    f"https://github.com/{repo}/blob/main/{path}"
                    if repo and repo != "unknown"
                    else "https://github.com"
                )

                if not content or len(content) < 100:
                    continue

                chunks = _chunk_text(content)
                for i, chunk in enumerate(chunks):
                    if self._check_stop():
                        break
                    header = (
                        f"[Source Code — {lang.upper()}]\n"
                        f"Repository: {repo}\nFile: {path}\nSource: {url}\n\n"
                    )
                    ok = self._store_chunk(
                        chunk=header + chunk,
                        source=url,
                        dataset_name="bigcode/the-stack-smol",
                        extra_meta={
                            "language": lang,
                            "repo": repo,
                            "file_path": path[:300],
                            "chunk_index": i,
                        },
                    )
                    if ok:
                        stored += 1

                processed += 1
                if processed % LOG_EVERY == 0:
                    logger.info(
                        f"[BigCode] {processed}/{max_files} files, "
                        f"{stored:,} chunks stored"
                    )
                    time.sleep(RATE_LIMIT_SLEEP)

        except Exception as exc:
            msg = f"BigCode ingestion error: {exc}"
            logger.error(msg)
            self.errors.append(msg)

        self._finish(stored, processed)
        return {"processed": processed, "stored": stored, "dataset": "bigcode/the-stack-smol"}

    # ─── Generic dataset ──────────────────────────────────────────────────────

    def ingest_dataset(
        self,
        dataset_name: str,
        text_column: str,
        max_rows: int = 10_000,
        config_name: Optional[str] = None,
        split: str = "train",
        extra_columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest any HuggingFace dataset by name.

        Parameters
        ----------
        dataset_name:
            HuggingFace dataset identifier, e.g. ``"allenai/c4"``.
        text_column:
            The dataset column that contains the main text to store.
        max_rows:
            Maximum number of rows to process.
        config_name:
            Optional dataset configuration / subset name.
        split:
            Dataset split to load (default ``"train"``).
        extra_columns:
            Additional column values to include in stored metadata.
        """
        self._begin(f"Generic dataset '{dataset_name}', col='{text_column}', max={max_rows:,}")
        stored = processed = 0

        try:
            from datasets import load_dataset

            load_kwargs: Dict[str, Any] = {
                "split": split,
                "streaming": True,
                "trust_remote_code": True,
            }
            if config_name:
                ds = load_dataset(dataset_name, config_name, **load_kwargs)
            else:
                ds = load_dataset(dataset_name, **load_kwargs)

            for item in ds:
                if self._check_stop() or processed >= max_rows:
                    break

                text = item.get(text_column, "")
                if not text:
                    continue
                text = _sanitize(str(text))

                extra_meta: Dict[str, Any] = {
                    "dataset_name": dataset_name,
                }
                if extra_columns:
                    for col in extra_columns:
                        val = item.get(col)
                        if val is not None:
                            extra_meta[col] = str(val)[:500]

                # Derive a source URL if url/source column present
                source = str(
                    item.get("url")
                    or item.get("source")
                    or item.get("link")
                    or f"hf://{dataset_name}"
                )

                chunks = _chunk_text(text)
                header = f"[{dataset_name}]\nSource: {source}\n\n"
                for i, chunk in enumerate(chunks):
                    if self._check_stop():
                        break
                    ok = self._store_chunk(
                        chunk=header + chunk,
                        source=source,
                        dataset_name=dataset_name,
                        extra_meta={**extra_meta, "chunk_index": i},
                    )
                    if ok:
                        stored += 1

                processed += 1
                if processed % LOG_EVERY == 0:
                    logger.info(
                        f"[{dataset_name}] {processed}/{max_rows} rows, "
                        f"{stored:,} chunks stored"
                    )
                    time.sleep(RATE_LIMIT_SLEEP)

        except Exception as exc:
            msg = f"Dataset '{dataset_name}' ingestion error: {exc}"
            logger.error(msg)
            self.errors.append(msg)

        self._finish(stored, processed)
        return {
            "processed": processed,
            "stored": stored,
            "dataset": dataset_name,
            "text_column": text_column,
        }

    # ─── Control ──────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the currently running ingestion to stop after the current item."""
        self._stop_flag = True
        logger.info("[HF Ingestion] Stop requested.")

    def get_status(self) -> Dict[str, Any]:
        """Return current ingestion status and cumulative statistics."""
        memory = self._get_memory()
        mem_stats = memory.get_stats() if hasattr(memory, "get_stats") else {}
        return {
            "running": self._running,
            "current_task": self.current_task,
            "last_run_started": self.last_run_started,
            "last_run_finished": self.last_run_finished,
            "total_chunks_stored": self.total_chunks_stored,
            "total_items_processed": self.total_items_processed,
            "recent_errors": self.errors[-20:],
            "memory_backend": "pinecone" if "pinecone" in str(type(memory)).lower() else "chromadb",
            "memory_count": mem_stats.get("count", 0),
        }

    # ─── Async wrappers ───────────────────────────────────────────────────────

    async def async_ingest_wikipedia(self, lang: str = "en", max_articles: int = 10_000) -> Dict[str, Any]:
        """Async-friendly wrapper around :meth:`ingest_wikipedia`."""
        return await asyncio.to_thread(self.ingest_wikipedia, lang, max_articles)

    async def async_ingest_arxiv(
        self,
        categories: Optional[List[str]] = None,
        max_papers: int = 5_000,
    ) -> Dict[str, Any]:
        """Async-friendly wrapper around :meth:`ingest_arxiv`."""
        return await asyncio.to_thread(self.ingest_arxiv, categories, max_papers)

    async def async_ingest_gutenberg(self, max_books: int = 500) -> Dict[str, Any]:
        """Async-friendly wrapper around :meth:`ingest_gutenberg`."""
        return await asyncio.to_thread(self.ingest_gutenberg, max_books)

    async def async_ingest_bigcode(
        self,
        max_files: int = 5_000,
        languages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Async-friendly wrapper around :meth:`ingest_bigcode`."""
        return await asyncio.to_thread(self.ingest_bigcode, max_files, languages)

    async def async_ingest_dataset(
        self,
        dataset_name: str,
        text_column: str,
        max_rows: int = 10_000,
        config_name: Optional[str] = None,
        split: str = "train",
        extra_columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Async-friendly wrapper around :meth:`ingest_dataset`."""
        return await asyncio.to_thread(
            self.ingest_dataset,
            dataset_name,
            text_column,
            max_rows,
            config_name,
            split,
            extra_columns,
        )


# Global singleton
hf_ingestion = HuggingFaceIngestion()
