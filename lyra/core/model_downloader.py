"""

Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.
Lyra Model Downloader
Downloads models from HuggingFace Hub with progress tracking.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Curated recommended models
RECOMMENDED_MODELS = {
    "mistral-7b-instruct-q4": {
        "name": "Mistral 7B Instruct Q4",
        "hf_repo": "TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
        "filename": "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "size_gb": 4.4,
        "description": "Fast, smart general purpose. Best for most tasks.",
        "recommended": True,
        "min_ram_gb": 8,
    },
    "llama3-8b-instruct-q4": {
        "name": "Llama 3 8B Instruct Q4",
        "hf_repo": "QuantFactory/Meta-Llama-3-8B-Instruct-GGUF",
        "filename": "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf",
        "size_gb": 4.9,
        "description": "Meta's Llama 3. Excellent reasoning and instruction following.",
        "recommended": True,
        "min_ram_gb": 8,
    },
    "deepseek-r1-7b-q4": {
        "name": "DeepSeek R1 Distill 7B Q4",
        "hf_repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "size_gb": 4.7,
        "description": "DeepSeek R1 reasoning model. Great for logic and coding.",
        "recommended": True,
        "min_ram_gb": 8,
    },
    "phi3-mini-q4": {
        "name": "Phi-3 Mini 3.8B Q4",
        "hf_repo": "microsoft/Phi-3-mini-4k-instruct-gguf",
        "filename": "Phi-3-mini-4k-instruct-q4.gguf",
        "size_gb": 2.2,
        "description": "Very fast. Great for low-RAM devices (4GB+).",
        "recommended": False,
        "min_ram_gb": 4,
    },
    "llama3-70b-q4": {
        "name": "Llama 3 70B Q4 (Large)",
        "hf_repo": "QuantFactory/Meta-Llama-3-70B-Instruct-GGUF",
        "filename": "Meta-Llama-3-70B-Instruct.Q4_K_M.gguf",
        "size_gb": 40.0,
        "description": "Maximum intelligence. Requires 48GB+ RAM or GPU.",
        "recommended": False,
        "min_ram_gb": 48,
    },
    "qwen2.5-7b-q4": {
        "name": "Qwen 2.5 7B Q4",
        "hf_repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "size_gb": 4.7,
        "description": "Alibaba's Qwen 2.5. Strong multilingual + coding.",
        "recommended": True,
        "min_ram_gb": 8,
    },
}


class ModelDownloader:
    """Download and manage AI models."""

    def __init__(self):
        self._active_downloads: Dict[str, Dict] = {}

    def get_recommended_models(self) -> list:
        """Return list of recommended models with download status."""
        result = []
        for model_id, info in RECOMMENDED_MODELS.items():
            model_path = MODELS_DIR / info["filename"]
            result.append({
                **info,
                "id": model_id,
                "downloaded": model_path.exists(),
                "local_path": str(model_path) if model_path.exists() else None,
                "download_progress": self._active_downloads.get(model_id, {}).get("progress", 0),
                "downloading": model_id in self._active_downloads,
            })
        return result

    async def download(
        self,
        model_id: str,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Download a model from HuggingFace.
        Streams progress to callback if provided.
        """
        if model_id not in RECOMMENDED_MODELS:
            return {"success": False, "error": f"Unknown model: {model_id}"}

        if model_id in self._active_downloads:
            return {"success": False, "error": "Already downloading"}

        info = RECOMMENDED_MODELS[model_id]
        model_path = MODELS_DIR / info["filename"]

        if model_path.exists():
            return {"success": True, "message": "Already downloaded", "path": str(model_path)}

        self._active_downloads[model_id] = {"progress": 0, "status": "starting"}

        try:
            result = await self._download_from_hf(model_id, info, model_path, progress_callback)
            return result
        finally:
            if model_id in self._active_downloads:
                del self._active_downloads[model_id]

    async def _download_from_hf(
        self, model_id: str, info: Dict, dest: Path, progress_cb
    ) -> Dict:
        """Download file from HuggingFace with progress."""
        try:
            from huggingface_hub import hf_hub_download
            import shutil

            loop = asyncio.get_event_loop()

            def _run():
                # Download to HF cache then copy
                cached = hf_hub_download(
                    repo_id=info["hf_repo"],
                    filename=info["filename"],
                    local_dir=str(MODELS_DIR),
                )
                return cached

            self._active_downloads[model_id]["status"] = "downloading"
            path = await loop.run_in_executor(None, _run)

            self._active_downloads[model_id] = {"progress": 100, "status": "done"}
            if progress_cb:
                await progress_cb({"model_id": model_id, "progress": 100, "status": "done"})

            return {"success": True, "path": path, "model_id": model_id}

        except ImportError:
            return {"success": False, "error": "huggingface_hub not installed. Run: pip install huggingface_hub"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def download_custom(self, url: str, filename: str) -> Dict:
        """Download a model from a custom URL (e.g., direct GGUF link)."""
        dest = MODELS_DIR / filename
        if dest.exists():
            return {"success": True, "message": "Already exists", "path": str(dest)}

        try:
            import httpx
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
            return {"success": True, "path": str(dest)}
        except Exception as e:
            if dest.exists():
                dest.unlink()
            return {"success": False, "error": str(e)}

    def delete_model(self, filename: str) -> Dict:
        """Delete a downloaded model file."""
        path = MODELS_DIR / filename
        if not path.exists():
            return {"success": False, "error": "Model not found"}
        try:
            path.unlink()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Global singleton
downloader = ModelDownloader()
