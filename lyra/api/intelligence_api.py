"""
Super-Intelligence RAG pipeline — REST API endpoints.

POST /api/intel/query          — ask a question
POST /api/intel/ingest/url     — ingest a URL
POST /api/intel/ingest/text    — ingest raw text
POST /api/intel/ingest/fineweb — start FineWeb-v2 ingestion (async)
POST /api/intel/ingest/starcoder — start StarCoder2 ingestion (async)
GET  /api/intel/stats          — Pinecone index stats
"""
import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/intel", tags=["intelligence"])

_pipeline = None
_ingestion_status: dict = {"running": False, "task": None, "progress": "idle"}


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        try:
            from lyra.intelligence.super_pipeline import SuperPipeline
            _pipeline = SuperPipeline()
            logger.info("SuperPipeline loaded.")
        except Exception as e:
            raise HTTPException(503, f"Pipeline unavailable: {e}. Check PINECONE_API_KEY.")
    return _pipeline


# ── Schemas ───────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    alpha: float = 0.7
    use_claude: bool = True

class IngestTextRequest(BaseModel):
    text: str
    source: str = "manual"

class IngestDatasetRequest(BaseModel):
    max_docs: int = 10_000


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/query")
async def query(req: QueryRequest):
    pipe = _get_pipeline()
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: pipe.query(
                req.question,
                top_k=req.top_k,
                alpha=req.alpha,
                use_claude=req.use_claude,
            )
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/ingest/text")
async def ingest_text(req: IngestTextRequest):
    pipe = _get_pipeline()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: pipe.ingest_text(req.text, source=req.source)
        )
        return {"success": True, "source": req.source}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/ingest/fineweb")
async def ingest_fineweb(req: IngestDatasetRequest, background_tasks: BackgroundTasks):
    if _ingestion_status["running"]:
        raise HTTPException(409, "Ingestion already running. Check /api/intel/stats.")
    pipe = _get_pipeline()

    def run():
        _ingestion_status["running"] = True
        _ingestion_status["task"] = "fineweb-v2"
        try:
            pipe.ingest_fineweb(max_docs=req.max_docs)
            _ingestion_status["progress"] = f"done ({req.max_docs:,} docs)"
        except Exception as e:
            _ingestion_status["progress"] = f"error: {e}"
        finally:
            _ingestion_status["running"] = False

    background_tasks.add_task(run)
    return {"started": True, "max_docs": req.max_docs, "check": "/api/intel/stats"}


@router.post("/ingest/starcoder")
async def ingest_starcoder(req: IngestDatasetRequest, background_tasks: BackgroundTasks):
    if _ingestion_status["running"]:
        raise HTTPException(409, "Ingestion already running.")
    pipe = _get_pipeline()

    def run():
        _ingestion_status["running"] = True
        _ingestion_status["task"] = "starcoder2"
        try:
            pipe.ingest_starcoder(max_docs=req.max_docs)
            _ingestion_status["progress"] = f"done ({req.max_docs:,} files)"
        except Exception as e:
            _ingestion_status["progress"] = f"error: {e}"
        finally:
            _ingestion_status["running"] = False

    background_tasks.add_task(run)
    return {"started": True, "max_docs": req.max_docs}


@router.get("/stats")
async def stats():
    pipe = _get_pipeline()
    try:
        index_stats = await asyncio.get_event_loop().run_in_executor(None, pipe.stats)
        return {
            "index": index_stats,
            "ingestion": _ingestion_status,
        }
    except Exception as e:
        raise HTTPException(500, str(e))
