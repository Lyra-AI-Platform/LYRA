"""
Lyra AI Platform — Main Application Server
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
See LICENSE for terms.

Run: python -m lyra.main  OR  uvicorn lyra.main:app --reload
"""
import logging
import os
import re
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
from lyra.api.oauth_api import router as oauth_router
from lyra.api.feedback_api import router as feedback_router
from lyra.api.wire_api import router as wire_router
from lyra.api.labs_api import router as labs_router
from lyra.api.admin_api import router as admin_router
from lyra.api.sites_api import router as sites_router
from lyra.api.billing_api import router as billing_router
from lyra.api.intelligence_api import router as intelligence_router
from lyra.api.market_api import router as market_router
from lyra.api.live_api import router as live_router
from lyra.api.pulse_api import router as pulse_router
from lyra.api.watch_api import router as watch_router
from lyra.api.watch_access import router as watch_account_router
from lyra.api.alerts_api import router as watch_alerts_router
from lyra.api.ads_api import router as ads_router
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

# The exceptions: siteverify is called from a customer's server with the secret key, and the
# training routes are for the owner. Neither has any reason to answer another site's page.
PRIVATE_AUTH_ROUTES = ("/api/auth/siteverify", "/api/auth/training")
# Account and admin APIs answer lyraauth.com's own pages and no other site's.
FIRST_PARTY_ROUTES = ("/api/users", "/api/oauth", "/api/sites", "/api/billing", "/api/admin", "/api/labs",
                      "/api/alerts", "/api/watch/account", "/api/feedback/admin")
FIRST_PARTY_ORIGINS = ("https://lyraauth.com",)


@app.middleware("http")
async def narrow_cors(request, call_next):
    response = await call_next(request)
    path = request.url.path
    private = path.startswith(PRIVATE_AUTH_ROUTES)
    if private or path.startswith(FIRST_PARTY_ROUTES):
        for name in [h for h in response.headers if h.lower().startswith("access-control-")]:
            if private or request.headers.get("origin") not in FIRST_PARTY_ORIGINS:
                del response.headers[name]
            elif name.lower() == "access-control-allow-origin":
                response.headers[name] = request.headers["origin"]
                response.headers["Vary"] = "Origin"
    return response

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


# Most of the site's 404s are vulnerability scanners asking for files no Lyra install has
# (.env, .git, WordPress, PHP admin panels). Answer them at once, before any page work, with a
# tiny response Cloudflare may keep, instead of a full not-found page each time.
SCANNER = re.compile(
    r"(^|/)\.(env|git|svn|hg|aws|ssh|docker|vscode|idea|DS_Store|htaccess|htpasswd)(\b|/|$)"
    r"|\.(php\d?|asp|aspx|jsp|cgi|sql|bak|old|swp)$"
    r"|^/(wp-|wordpress|xmlrpc|phpmyadmin|pma|cgi-bin|vendor/phpunit|actuator|server-status|boaform|owa/|"
    r"autodiscover|ecp/|remote/login|hudson|jenkins|solr/|console/|manager/html|telescope|_ignition)", re.I)


@app.middleware("http")
async def scanner_guard(request, call_next):
    if SCANNER.search(request.url.path):
        return Response("Not found", status_code=404, media_type="text/plain",
                        headers={"Cache-Control": "public, max-age=86400", "X-Robots-Tag": "noindex"})
    return await call_next(request)


# Members-only pages are withheld on the server until the visitor is signed in and entitled.
app.middleware("http")(page_access.guard)

# COSHH moved to its own site, ChemWarden. Old links and bookmarks land there instead of a 404.
# Registered after the page guard so it runs first (the last middleware added is the outermost).
CHEMWARDEN = "https://chemwarden.com"


@app.middleware("http")
async def coshh_moved(request, call_next):
    path = request.url.path.lower().rstrip("/")
    if path in ("/coshh", "/pages/coshh.html") or path.startswith("/coshh/") or path.startswith("/api/coshh"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "COSHH moved to https://chemwarden.com"}, status_code=410)
        return Response(status_code=301, headers={"Location": CHEMWARDEN, "Cache-Control": "public, max-age=86400"})
    return await call_next(request)

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
app.include_router(oauth_router)
app.include_router(feedback_router)
app.include_router(wire_router)
app.include_router(labs_router)
app.include_router(admin_router)
app.include_router(sites_router)
app.include_router(billing_router)
app.include_router(intelligence_router)
app.include_router(market_router)
app.include_router(pulse_router)
app.include_router(live_router)
app.include_router(watch_router)
app.include_router(watch_account_router)
app.include_router(watch_alerts_router)
app.include_router(ads_router)


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


@app.get("/market", include_in_schema=False)
async def old_market_address(request: Request):
    """The Tremor Index lives under /tremor/. Old links keep working."""
    from starlette.responses import RedirectResponse
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/tremor/reading{query}", status_code=301)


@app.get("/tremor/reading", response_class=HTMLResponse)
async def serve_market():
    market_path = FRONTEND_DIR / "templates" / "market.html"
    if market_path.exists():
        return FileResponse(str(market_path))
    return HTMLResponse("<h1>Market Expert UI not found</h1>")


def _ollama_model() -> str:
    from lyra.core import ollama_backend
    return f"ollama:{ollama_backend.model()}" if ollama_backend.enabled() else ""


@app.get("/health")
@app.get("/api/health")
async def health(request: Request):
    # The internals (which model, memory, learning loops) are for the machine itself; the
    # public only learns that the site is up and which commit is running.
    from lyra.api.version import commit
    if not is_local_request(request):
        return {"status": "running", "platform": "Lyra AI", "commit": commit()}
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
        "commit": commit(),
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
    from lyra.watch.alerts import alert_loop
    alert_loop.start()
    from lyra.watch.live import loop as live_loop, signals_loop
    live_loop.start()
    signals_loop.start()
    # Global newswire: news in every language and new research, collected for as long as Lyra runs
    from lyra.newswire.collector import collector as newswire
    newswire.start()
    from lyra.market.pulse_loop import pulse_loop
    pulse_loop.start()

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
    from lyra.watch.alerts import alert_loop
    alert_loop.stop()
    from lyra.newswire.collector import collector as newswire
    newswire.stop()
    from lyra.market.pulse_loop import pulse_loop
    pulse_loop.stop()
    from lyra.watch.live import loop as live_loop, signals_loop
    live_loop.stop()
    signals_loop.stop()
    await engine.unload_model()


# Pages use inline scripts, so 'unsafe-inline' stays; everything else is locked to this site
# (plus Google Fonts, Stripe Checkout and the Google / Apple / GitHub sign-in pages, which
# Apple reaches with a form post back to us). Lyra Labs may also call a model on the visitor's
# own computer ("On this device"), so its pages alone may fetch from localhost.
CLOUDFLARE_ANALYTICS_SCRIPT = "https://static.cloudflareinsights.com"
CLOUDFLARE_ANALYTICS_BEACON = "https://cloudflareinsights.com"


def csp(path: str = "") -> str:
    from lyra.api import adsense
    ads = adsense.csp_extra()   # Google's ad servers, only while AdSense is switched on
    local = "http://localhost:* http://127.0.0.1:* " if path.startswith("/labs") else ""
    return (f"default-src 'self'; script-src 'self' 'unsafe-inline' {CLOUDFLARE_ANALYTICS_SCRIPT} {ads}; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: https:; connect-src 'self' {CLOUDFLARE_ANALYTICS_BEACON} {local}{ads}; "
            f"frame-src 'self' {ads}; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'self' https://checkout.stripe.com https://accounts.google.com https://appleid.apple.com https://github.com; object-src 'none'; "
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
            response.headers.setdefault("Content-Security-Policy", csp(request.url.path))
        if request.method in ("GET", "HEAD") and response.status_code == 200:
            response.headers.setdefault("Cache-Control", cache_policy(request.url.path))
        return response

    @app.middleware("http")
    async def canonical_host(request, call_next):
        # One address for search engines. Only page loads move: a redirected POST loses its body.
        host = request.headers.get("host", "").lower()
        if host.startswith("www.") and request.method in ("GET", "HEAD"):
            query = f"?{request.url.query}" if request.url.query else ""
            from starlette.responses import RedirectResponse
            return RedirectResponse(f"https://{host[4:]}{request.url.path}{query}", status_code=301)
        return await call_next(request)

    STATIC_EXT = (".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".woff2", ".txt", ".xml")

    def cache_policy(path: str) -> str:
        """How long browsers and Cloudflare may keep a public file. Members-only pages set
        no-store themselves (page_access.py) and APIs set their own, so this only decides for
        the rest. Static files are kept a day at the edge; public pages five minutes, served
        stale while Cloudflare refetches, so a burst of visitors costs the NAS one request."""
        if path == "/" or path.startswith("/api/") or page_access.rule_for(path):
            return "no-cache"
        if path.lower().endswith(STATIC_EXT):
            return "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
        return "public, max-age=60, s-maxage=300, stale-while-revalidate=86400"

    @app.get("/ads.txt", include_in_schema=False)
    async def ads_txt():
        from lyra.api import adsense
        body = adsense.ads_txt()
        if not body:
            return Response("Not found", status_code=404, media_type="text/plain")
        return Response(body, media_type="text/plain", headers={"Cache-Control": "public, max-age=3600"})

    @app.middleware("http")
    async def adsense_tags(request, call_next):
        """Put the AdSense tags into public pages (see lyra/api/adsense.py)."""
        from lyra.api import adsense
        response = await call_next(request)
        if (request.method != "GET" or response.status_code != 200 or not adsense.wants_ads(request.url.path)
                or not response.headers.get("content-type", "").startswith("text/html")):
            return response
        from lyra.db.database import SessionLocal
        db = SessionLocal()
        try:
            if adsense.ad_free(request, db):
                return response
        finally:
            db.close()
        body = b"".join([chunk async for chunk in response.body_iterator])
        body = body.replace(b"</head>", adsense.head_tags() + b"</head>", 1)
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "etag")}
        headers["Vary"] = "Cookie"
        return Response(body, status_code=200, headers=headers, media_type="text/html")

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
