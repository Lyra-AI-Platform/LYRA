"""
Lyra Models API
Endpoints for model management: list, load, download, delete.
"""
import logging
from typing import Optional, Dict
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from lyra.core.engine import engine
from lyra.core.model_downloader import downloader
from lyra.models.lyra_models import list_models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/models", tags=["models"])


class LoadModelRequest(BaseModel):
    model_name: str
    context_length: int = 8192
    gpu_layers: int = -1


class DownloadRequest(BaseModel):
    model_id: str


class CustomDownloadRequest(BaseModel):
    url: str
    filename: str


@router.get("/")
async def get_models():
    """List all available local models + Lyra personalities."""
    local_models = engine.get_available_models()
    lyra_personas = list_models()
    recommended = downloader.get_recommended_models()

    return {
        "local_models": local_models,
        "lyra_personas": lyra_personas,
        "recommended_downloads": recommended,
        "loaded_model": engine.loaded_model_name,
        "model_type": engine.model_type,
    }


@router.post("/load")
async def load_model(request: LoadModelRequest):
    """Load a model into memory."""
    result = await engine.load_model(
        request.model_name,
        {
            "context_length": request.context_length,
            "gpu_layers": request.gpu_layers,
        },
    )
    return result


@router.post("/unload")
async def unload_model():
    """Unload current model from memory."""
    await engine.unload_model()
    return {"status": "unloaded"}


@router.get("/status")
async def model_status():
    """Get current model status."""
    return {
        "loaded": engine.loaded_model_name is not None,
        "model_name": engine.loaded_model_name,
        "model_type": engine.model_type,
    }


@router.post("/download")
async def download_model(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Start downloading a recommended model."""
    # Start download in background
    background_tasks.add_task(_run_download, request.model_id)
    return {
        "status": "started",
        "model_id": request.model_id,
        "message": "Download started in background. Check /api/models/download/status for progress.",
    }


@router.post("/download/custom")
async def download_custom(request: CustomDownloadRequest, background_tasks: BackgroundTasks):
    """Download a model from a custom URL."""
    background_tasks.add_task(
        downloader.download_custom, request.url, request.filename
    )
    return {"status": "started", "filename": request.filename}


@router.get("/download/status")
async def download_status():
    """Get download progress for all active downloads."""
    return {
        "active_downloads": downloader._active_downloads,
        "recommended": downloader.get_recommended_models(),
    }


@router.delete("/{filename}")
async def delete_model(filename: str):
    """Delete a downloaded model."""
    result = downloader.delete_model(filename)
    return result


async def _run_download(model_id: str):
    """Background download task."""
    result = await downloader.download(model_id)
    if result["success"]:
        logger.info(f"Model downloaded: {model_id}")
    else:
        logger.error(f"Model download failed: {model_id} — {result.get('error')}")
