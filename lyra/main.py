"""
Lyra AI Platform — Main Application Server
Run: python -m lyra.main  OR  uvicorn lyra.main:app --reload
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

from lyra.api.chat import router as chat_router
from lyra.api.models_api import router as models_router
from lyra.api.memory_api import router as memory_router
from lyra.api.learning_api import router as learning_router
from lyra.api.telemetry_api import router as telemetry_router
from lyra.api.graph_api import router as graph_router
from lyra.api.cognition_api import router as cognition_router
from lyra.api.experiment_api import router as experiment_router
from lyra.authenticator.api import router as auth_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
FRONTEND_DIR = ROOT / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
DATA_DIR = ROOT / "data"

for d in [DATA_DIR / "models", DATA_DIR / "uploads", DATA_DIR / "memory", DATA_DIR / "logs"]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Lyra AI Platform", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(chat_router)
app.include_router(models_router)
app.include_router(memory_router)
app.include_router(learning_router)
app.include_router(telemetry_router)
app.include_router(graph_router)
app.include_router(cognition_router)
app.include_router(experiment_router)
app.include_router(auth_router)


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index_path = FRONTEND_DIR / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>Lyra starting up...</h1>")


@app.get("/api/health")
async def health():
    from lyra.core.engine import engine
    from lyra.memory.vector_memory import memory
    from lyra.core.auto_learner import auto_learner
    mem_stats = memory.get_stats()
    return {
        "status": "running",
        "platform": "Lyra AI",
        "version": "3.0.0",
        "model_loaded": engine.loaded_model_name is not None,
        "memory_count": mem_stats.get("count", 0),
        "learning_running": auto_learner.running,
        "facts_learned": auto_learner.learned_count,
    }


@app.on_event("startup")
async def on_startup():
    from lyra.core.integrity import checker
    checker.startup_check()
    from lyra.core.auto_learner import auto_learner
    auto_learner.start()
    from lyra.core.synthesis_engine import synthesizer
    synthesizer.start()
    from lyra.authenticator.engine import challenge_engine
    challenge_engine.start()
    from lyra.core.cognition_engine import cognition_engine
    cognition_engine.start()
    from lyra.core.experiment_engine import experiment_engine
    experiment_engine.start()
    from lyra.core.self_awareness import self_awareness
    self_awareness.start()
    from lyra.core.language_backbone import language_backbone
    await language_backbone.initialize()
    logger.info("Lyra AI Platform started — http://0.0.0.0:8080")


@app.on_event("shutdown")
async def on_shutdown():
    from lyra.core.auto_learner import auto_learner
    from lyra.core.synthesis_engine import synthesizer
    from lyra.core.cognition_engine import cognition_engine
    from lyra.core.experiment_engine import experiment_engine
    from lyra.core.self_awareness import self_awareness
    auto_learner.stop()
    synthesizer.stop()
    cognition_engine.stop()
    experiment_engine.stop()
    self_awareness.stop()


def main():
    port = int(os.environ.get("LYRA_PORT", 8080))
    host = os.environ.get("LYRA_HOST", "0.0.0.0")
    uvicorn.run("lyra.main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
