"""
Lyra AI Platform — HuggingFace Ingestion API
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Endpoints to trigger massive knowledge ingestion from open datasets.
All long-running operations run as FastAPI BackgroundTasks so the HTTP
response is immediate and the caller can poll /api/ingestion/status.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


# ─── Request / Response models ────────────────────────────────────────────────

class WikipediaRequest(BaseModel):
    lang: str = Field(default="en", description="Wikipedia language code (e.g. 'en', 'de', 'fr')")
    max_articles: int = Field(default=10_000, ge=1, le=5_000_000, description="Max articles to ingest")


class ArxivRequest(BaseModel):
    categories: List[str] = Field(
        default=["cs.AI", "cs.LG", "physics"],
        description="ArXiv category codes to filter on",
    )
    max_papers: int = Field(default=5_000, ge=1, le=1_000_000, description="Max papers to ingest")


class GutenbergRequest(BaseModel):
    max_books: int = Field(default=500, ge=1, le=100_000, description="Max books to ingest")


class BigCodeRequest(BaseModel):
    max_files: int = Field(default=5_000, ge=1, le=1_000_000, description="Max source files to ingest")
    languages: Optional[List[str]] = Field(
        default=None,
        description="Programming languages to filter (e.g. ['python', 'rust']). None = all.",
    )


class DatasetRequest(BaseModel):
    dataset_name: str = Field(..., description="HuggingFace dataset name (e.g. 'allenai/c4')")
    text_column: str = Field(..., description="Column name that contains the main text")
    max_rows: int = Field(default=10_000, ge=1, le=10_000_000, description="Max rows to ingest")
    config_name: Optional[str] = Field(default=None, description="Optional dataset configuration/subset")
    split: str = Field(default="train", description="Dataset split to load")
    extra_columns: Optional[List[str]] = Field(
        default=None,
        description="Additional columns to store as metadata",
    )


class IngestionResponse(BaseModel):
    status: str
    message: str
    task: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_ingestion_status():
    """
    Return current ingestion progress and cumulative statistics.

    Includes whether an ingestion is currently running, which task is active,
    how many chunks have been stored this session, and recent errors.
    """
    from lyra.data.hf_ingestion import hf_ingestion
    return hf_ingestion.get_status()


@router.post("/wikipedia", response_model=IngestionResponse)
async def start_wikipedia_ingestion(
    request: WikipediaRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start ingesting Wikipedia articles in the background.

    Uses the HuggingFace ``wikipedia`` dataset (streaming mode).
    Progress can be monitored via GET /api/ingestion/status.
    """
    from lyra.data.hf_ingestion import hf_ingestion

    if hf_ingestion._running:
        raise HTTPException(
            status_code=409,
            detail=f"Ingestion already running: '{hf_ingestion.current_task}'. "
                   "POST /api/ingestion/stop first.",
        )

    background_tasks.add_task(
        hf_ingestion.ingest_wikipedia,
        lang=request.lang,
        max_articles=request.max_articles,
    )
    return IngestionResponse(
        status="started",
        message=f"Wikipedia ({request.lang}) ingestion started — up to {request.max_articles:,} articles",
        task=f"wikipedia/{request.lang}",
    )


@router.post("/arxiv", response_model=IngestionResponse)
async def start_arxiv_ingestion(
    request: ArxivRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start ingesting ArXiv papers in the background.

    Filters to the specified category codes (e.g. cs.AI, cs.LG, physics).
    """
    from lyra.data.hf_ingestion import hf_ingestion

    if hf_ingestion._running:
        raise HTTPException(
            status_code=409,
            detail=f"Ingestion already running: '{hf_ingestion.current_task}'. "
                   "POST /api/ingestion/stop first.",
        )

    background_tasks.add_task(
        hf_ingestion.ingest_arxiv,
        categories=request.categories,
        max_papers=request.max_papers,
    )
    return IngestionResponse(
        status="started",
        message=(
            f"ArXiv ingestion started — categories={request.categories}, "
            f"max={request.max_papers:,} papers"
        ),
        task="arxiv",
    )


@router.post("/gutenberg", response_model=IngestionResponse)
async def start_gutenberg_ingestion(
    request: GutenbergRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start ingesting Project Gutenberg public-domain books in the background.
    """
    from lyra.data.hf_ingestion import hf_ingestion

    if hf_ingestion._running:
        raise HTTPException(
            status_code=409,
            detail=f"Ingestion already running: '{hf_ingestion.current_task}'. "
                   "POST /api/ingestion/stop first.",
        )

    background_tasks.add_task(
        hf_ingestion.ingest_gutenberg,
        max_books=request.max_books,
    )
    return IngestionResponse(
        status="started",
        message=f"Gutenberg ingestion started — up to {request.max_books:,} books",
        task="gutenberg",
    )


@router.post("/bigcode", response_model=IngestionResponse)
async def start_bigcode_ingestion(
    request: BigCodeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start ingesting source-code files from BigCode/The Stack in the background.

    Set the ``HUGGINGFACE_TOKEN`` environment variable to access the full Stack.
    Without a token the smaller ``the-stack-smol`` sample is used.
    """
    from lyra.data.hf_ingestion import hf_ingestion

    if hf_ingestion._running:
        raise HTTPException(
            status_code=409,
            detail=f"Ingestion already running: '{hf_ingestion.current_task}'. "
                   "POST /api/ingestion/stop first.",
        )

    background_tasks.add_task(
        hf_ingestion.ingest_bigcode,
        max_files=request.max_files,
        languages=request.languages,
    )
    lang_str = ", ".join(request.languages) if request.languages else "all languages"
    return IngestionResponse(
        status="started",
        message=f"BigCode ingestion started — {lang_str}, up to {request.max_files:,} files",
        task="bigcode",
    )


@router.post("/dataset", response_model=IngestionResponse)
async def start_dataset_ingestion(
    request: DatasetRequest,
    background_tasks: BackgroundTasks,
):
    """
    Ingest any HuggingFace dataset by name.

    Provide the dataset identifier, the name of the text column, and optional
    configuration / split.  Example::

        POST /api/ingestion/dataset
        {
            "dataset_name": "allenai/c4",
            "text_column": "text",
            "max_rows": 50000,
            "config_name": "en",
            "split": "train"
        }
    """
    from lyra.data.hf_ingestion import hf_ingestion

    if hf_ingestion._running:
        raise HTTPException(
            status_code=409,
            detail=f"Ingestion already running: '{hf_ingestion.current_task}'. "
                   "POST /api/ingestion/stop first.",
        )

    background_tasks.add_task(
        hf_ingestion.ingest_dataset,
        dataset_name=request.dataset_name,
        text_column=request.text_column,
        max_rows=request.max_rows,
        config_name=request.config_name,
        split=request.split,
        extra_columns=request.extra_columns,
    )
    return IngestionResponse(
        status="started",
        message=(
            f"Dataset '{request.dataset_name}' ingestion started — "
            f"column='{request.text_column}', max={request.max_rows:,} rows"
        ),
        task=request.dataset_name,
    )


@router.post("/stop", response_model=IngestionResponse)
async def stop_ingestion():
    """
    Stop any currently running ingestion after the current item finishes.

    The running background task checks the stop flag between items, so
    ingestion will halt within a few seconds of this call.
    """
    from lyra.data.hf_ingestion import hf_ingestion

    if not hf_ingestion._running:
        return IngestionResponse(
            status="idle",
            message="No ingestion is currently running.",
        )

    hf_ingestion.stop()
    return IngestionResponse(
        status="stopping",
        message=f"Stop signal sent to task '{hf_ingestion.current_task}'. "
                "It will finish the current item and then halt.",
    )
