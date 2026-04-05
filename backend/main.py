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
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

from routers import auth, overview, finance, chatters, events, plans, kpi, ai, admin, settings, structure, shifts, teams  # noqa: E402
from database import engine, Base, AsyncSessionLocal  # noqa: E402

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
app.include_router(shifts.router)
app.include_router(teams.router)


# ── Startup: create missing tables ───────────────────────────────────────────

@app.on_event("startup")
async def _create_tables():
    import models  # noqa: F401 – ensure all models are registered
    from schema_patch import apply_schema_patches
    from team_bootstrap import bootstrap_teams, assign_transactions_by_notion_database
    from sqlalchemy import select

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await apply_schema_patches(engine)
        async with AsyncSessionLocal() as db:
            await bootstrap_teams(db)
            # Привязка team_id, если у транзакций уже есть notion_database_id
            await assign_transactions_by_notion_database(db)
            # Опционально: подтянуть notion_database_id из API — POST /api/v1/teams/reconcile-notion
        if os.getenv("NOTION_BACKFILL_ON_STARTUP") == "1":
            from team_bootstrap import backfill_notion_database_id_from_notion_api
            from models import Tenant as TenantModel

            async with AsyncSessionLocal() as db:
                r = await db.execute(select(TenantModel.id, TenantModel.notion_token))
                for tid, token in r.all():
                    if token and str(token).strip():
                        try:
                            await backfill_notion_database_id_from_notion_api(
                                db, tid, str(token), limit=100
                            )
                        except Exception as e:
                            logger.warning("startup notion backfill tenant=%s: %s", tid, e)
                await assign_transactions_by_notion_database(db)
    except Exception as exc:
        logger.warning("startup schema/teams warning (non-fatal): %s", exc, exc_info=True)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "2.0.0"}
