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

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
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
from lyra.api.intelligence_api import router as intelligence_router
from lyra.api.market_api import router as market_router
from lyra.api.watch_api import router as watch_router
from lyra.api.watch_access import router as watch_account_router
from lyra.api.ads_api import router as ads_router
from lyra.api.coshh_api import router as coshh_router
from lyra.api import page_access

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
FRONTEND_DIR = ROOT / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
DATA_DIR = ROOT / "data"
WEBSITE_DIR = ROOT / "website"
# On a VPS nginx serves website/; in the Docker/NAS setup the app serves it itself.
SERVE_WEBSITE = os.environ.get("LYRA_SERVE_WEBSITE") == "1"

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
    # Any site may call the public APIs (the LyraAuth widget runs on customers' sites), but
    # sign-in is a bearer token, never a cookie, so no credentials are allowed cross-site.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The engine's control APIs (load and delete models, wipe memory, crawl any URL, set tokens,
# claim ownership) are for the machine Lyra runs on. Requests from anywhere else, including
# everything arriving through the Cloudflare tunnel, get a 404.
LOCAL_ONLY = ("/api/models", "/api/memory", "/api/ingestion", "/api/learning", "/api/graph",
              "/api/telemetry", "/api/intel", "/api/cognition", "/api/quantum", "/api/experiments",
              "/api/self", "/api/owner", "/docs", "/redoc", "/openapi.json")
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded")


def is_local_request(request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") and not any(h in request.headers for h in PROXY_HEADERS)


@app.middleware("http")
async def local_only_guard(request, call_next):
    path = request.url.path
    if any(path == p or path.startswith(p + "/") for p in LOCAL_ONLY) and not is_local_request(request):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


# Members-only pages are withheld on the server until the visitor is signed in and entitled.
app.middleware("http")(page_access.guard)

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
app.include_router(intelligence_router)
app.include_router(market_router)
app.include_router(watch_router)
app.include_router(watch_account_router)
app.include_router(ads_router)
app.include_router(coshh_router)


FAVICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           "<text y='.9em' font-size='90'>\u2726</text></svg>")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Browsers ask for this on every page that doesn't name an icon; answer instead of a 404.
    return Response(FAVICON, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    if SERVE_WEBSITE:
        home = page_access.signed_in_home(request, WEBSITE_DIR)
        if home:
            return home
        return FileResponse(str(WEBSITE_DIR / "index.html"))
    index_path = FRONTEND_DIR / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>Lyra starting up...</h1>")


@app.get("/market", response_class=HTMLResponse)
async def serve_market():
    market_path = FRONTEND_DIR / "templates" / "market.html"
    if market_path.exists():
        return FileResponse(str(market_path))
    return HTMLResponse("<h1>Market Expert UI not found</h1>")


def _ollama_model() -> str:
    from lyra.core import ollama_backend
    return f"ollama:{ollama_backend.model()}" if ollama_backend.enabled() else ""


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
        "chat_model": engine.loaded_model_name or _ollama_model() or ("claude" if os.getenv("ANTHROPIC_API_KEY") else "language-backbone"),
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

    # Grade matured Tremor Index readings and retrain (every 6h)
    from lyra.market.expert import learning_loop
    learning_loop.start()
    from lyra.watch.service import refresh_loop
    refresh_loop.start()
    from lyra.watch.live import loop as live_loop, signals_loop
    live_loop.start()
    signals_loop.start()

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
    from lyra.market.expert import learning_loop
    learning_loop.stop()
    from lyra.watch.service import refresh_loop
    refresh_loop.stop()
    from lyra.watch.live import loop as live_loop, signals_loop
    live_loop.stop()
    signals_loop.stop()
    await engine.unload_model()


# Pages use inline scripts, so 'unsafe-inline' stays; everything else is locked to this site
# (plus Google Fonts and Stripe Checkout).
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: https:; connect-src 'self'; "
       "frame-ancestors 'self'; base-uri 'self'; form-action 'self' https://checkout.stripe.com; object-src 'none'; "
       "upgrade-insecure-requests")

if SERVE_WEBSITE:
    @app.get("/widget.js")
    async def serve_widget():
        return FileResponse(str(ROOT / "lyra" / "authenticator" / "frontend" / "lyraauth.js"),
                            media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    # Mounted last so every API route above takes priority over static files.
    app.mount("/", StaticFiles(directory=str(WEBSITE_DIR), html=True), name="website")


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
