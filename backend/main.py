import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("skynet")

app = FastAPI(
    title="Skynet SaaS API",
    description="FastAPI backend for Skynet — OnlyFans agency analytics platform",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

_vercel_url = os.getenv("FRONTEND_URL", "")
_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://flow-of.vercel.app",
    "https://www.flow-of.vercel.app",
]
if _vercel_url and _vercel_url not in _origins:
    _origins.append(_vercel_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

from routers import auth, overview, finance, chatters, events, plans, kpi, ai, admin, settings, structure  # noqa: E402

app.include_router(auth.router)
app.include_router(overview.router)
app.include_router(finance.router)
app.include_router(chatters.router)
app.include_router(events.router)
app.include_router(plans.router)
app.include_router(kpi.router)
app.include_router(ai.router)
app.include_router(admin.router)
app.include_router(settings.router)
app.include_router(structure.router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "2.0.0"}
