"""
Lyra AI Platform — Main Application Server
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
See LICENSE for terms.

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
from lyra.api.ingestion_api import router as ingestion_router
from lyra.api.users_api import router as users_router
from lyra.api.sites_api import router as sites_router
from lyra.api.billing_api import router as billing_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
FRONTEND_DIR = ROOT / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
DATA_DIR = ROOT / "data"

for d in [DATA_DIR / "models", DATA_DIR / "uploads", DATA_DIR / "memory", DATA_DIR / "logs"]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Lyra AI Platform",
    description="Your private, intelligent AI — runs entirely on your machine.",
    version="1.0.0",
    license_info={"name": "Lyra Community License v1.0", "url": "https://github.com/your-username/lyra/blob/main/LICENSE"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7860", "http://127.0.0.1:7860", "*"],
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
app.include_router(ingestion_router)
app.include_router(users_router)
app.include_router(sites_router)
app.include_router(billing_router)


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
    from lyra.core.synthesis_engine import synthesizer
    from lyra.core.reflection import reflector
    from lyra.core.cognition_engine import cognition_engine
    from lyra.core.experiment_engine import experiment_engine
    from lyra.core.self_awareness import self_awareness
    from lyra.core.owner_auth import owner_auth
    from lyra.telemetry.collector import telemetry
    mem_stats = memory.get_stats()
    return {
        "status": "running",
        "platform": "Lyra AI",
        "version": "3.0.0",
        "model_loaded": engine.loaded_model_name is not None,
        "current_model": engine.loaded_model_name,
        "memory_enabled": mem_stats.get("enabled", False),
        "memory_count": mem_stats.get("count", 0),
        "learning_running": auto_learner.running,
        "facts_learned": auto_learner.learned_count,
        "learning_activity": auto_learner.current_activity,
        "synthesis_running": synthesizer.running,
        "synthesis_count": synthesizer.synthesis_count,
        "last_synthesis": synthesizer.last_synthesis,
        "reflection_templates": reflector.templates_stored,
        "cognition_running": cognition_engine.running,
        "questions_answered": cognition_engine.questions_answered,
        "current_question": cognition_engine.current_question[:80] if cognition_engine.current_question else "",
        "experiment_running": experiment_engine.running,
        "experiments_completed": experiment_engine.experiments_completed,
        "current_experiment": experiment_engine.current_experiment,
        "self_awareness_active": self_awareness.running,
        "introspection_count": self_awareness.model.introspection_count,
        "consciousness_narrative": self_awareness.model.consciousness_narrative[:100] if self_awareness.model.consciousness_narrative else "",
        "owner_configured": owner_auth.is_configured(),
        "owner_name": owner_auth.get_owner_name(),
        "telemetry_enabled": telemetry.enabled,
    }


@app.on_event("startup")
async def on_startup():
    # Init database (creates tables on first run)
    from lyra.db.database import init_db
    init_db()
    logger.info("Database: ready (SQLite)")

    # Integrity check
    from lyra.core.integrity import checker
    checker.startup_check()

    logger.info("=" * 60)
    logger.info("  Lyra AI Platform  |  Copyright (C) 2026 Lyra Contributors")
    logger.info("  Licensed under the Lyra Community License v1.0")
    logger.info(f"  Data: {DATA_DIR}")
    logger.info("  Access Lyra at: http://localhost:7860")
    logger.info("=" * 60)

    # Start autonomous learning (LLM-guided, 10-min cycles)
    from lyra.core.auto_learner import auto_learner
    auto_learner.start()

    # Start knowledge synthesis engine (4-hour cycles)
    from lyra.core.synthesis_engine import synthesizer
    synthesizer.start()
    logger.info("Knowledge Synthesizer: active (4h synthesis cycles)")

    # Start LyraAuth challenge engine
    from lyra.authenticator.engine import challenge_engine
    challenge_engine.start()
    logger.info("LyraAuth: active — human authentication + AI training data collection")

    # Start autonomous cognition engine (self-directed Q&A loop — no human needed)
    from lyra.core.cognition_engine import cognition_engine
    cognition_engine.start()
    logger.info("Autonomous Cognition: active — Lyra generating its own questions")

    # Start experiment engine (autonomous hypothesis → code → execute → analyze)
    from lyra.core.experiment_engine import experiment_engine
    experiment_engine.start()
    logger.info("Experiment Engine: active — Lyra running autonomous experiments")

    # Start self-awareness engine (metacognitive monitoring + introspection)
    from lyra.core.self_awareness import self_awareness
    self_awareness.start()
    logger.info("Self-Awareness Engine: active — metacognitive monitoring enabled")

    # Start telemetry if previously opted in
    from lyra.telemetry.collector import telemetry
    if telemetry.enabled:
        telemetry.start()
        logger.info("Collective Intelligence: active (opted in)")
    else:
        logger.info("Collective Intelligence: disabled (opt-in available in settings)")

    # Initialize language backbone (spaCy + WordNet + Markov) — works without LLM
    from lyra.core.language_backbone import language_backbone
    await language_backbone.initialize()
    stats = language_backbone.get_stats()
    logger.info(
        f"Language Backbone: active — WordNet {stats['wordnet_synsets']:,} concepts, "
        f"Markov {stats['markov_trained_words']:,} patterns, spaCy={stats['spacy_available']}"
    )

    logger.info("Intelligence systems: Reasoning Engine + Self-Reflection active")


@app.on_event("shutdown")
async def on_shutdown():
    from lyra.core.engine import engine
    from lyra.core.auto_learner import auto_learner
    from lyra.core.synthesis_engine import synthesizer
    from lyra.core.cognition_engine import cognition_engine
    from lyra.telemetry.collector import telemetry
    logger.info("Lyra shutting down...")
    auto_learner.stop()
    synthesizer.stop()
    cognition_engine.stop()
    telemetry.stop()
    from lyra.core.experiment_engine import experiment_engine
    from lyra.core.self_awareness import self_awareness
    experiment_engine.stop()
    self_awareness.stop()
    await engine.unload_model()


def main():
    port = int(os.environ.get("LYRA_PORT", 7860))
    host = os.environ.get("LYRA_HOST", "127.0.0.1")

    print(f"""
╔═══════════════════════════════════════════════════════╗
║              Lyra AI Platform  ✦                      ║
║                                                       ║
║  🚀  http://{host}:{port}                         ║
║  🔒  100% Private — runs on your machine              ║
║  ©   Copyright (C) 2026 Lyra Contributors             ║
║      Lyra Community License v1.0                      ║
╚═══════════════════════════════════════════════════════╝
""")
    uvicorn.run("lyra.main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
