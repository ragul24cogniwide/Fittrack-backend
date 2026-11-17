import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes import (
    ai, auth, cycle, dashboard, history, masturbation, nutrition, sleep, vitals, workouts,
)
from app.core.config import _is_hosted, settings
from app.db.base import Base
from app.db.migrate import add_missing_columns
from app.db.seed import seed_demo_data
from app.db.session import AsyncSessionLocal, engine
import app.models  # Ensures all 7 models are registered on Base.metadata


log = logging.getLogger("fittrack.keepalive")


def keep_alive_url() -> str:
    """Public /ping URL of this server when hosted (Render sets RENDER_EXTERNAL_URL), else ''."""
    if not _is_hosted or settings.KEEP_ALIVE_SECONDS <= 0:
        return ""
    base = (settings.PUBLIC_BASE_URL or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    return f"{base}/ping" if base else ""


async def keep_alive(url: str, every: int) -> None:
    """Requests our own public URL so Render sees traffic and doesn't put the service to sleep."""
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await asyncio.sleep(every)
            try:
                await client.get(url)
            except Exception as err:  # a missed ping is harmless; try again next round
                log.warning("keep-alive ping failed: %s", err)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Creates any missing tables in NeonDB on startup (idempotent) and starts the keep-alive ping."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(add_missing_columns)
    url = keep_alive_url()
    task = asyncio.create_task(keep_alive(url, settings.KEEP_ALIVE_SECONDS)) if url else None
    if task:
        log.info("keep-alive: pinging %s every %ss", url, settings.KEEP_ALIVE_SECONDS)
    yield
    if task:
        task.cancel()
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-ready FastAPI backend with NeonDB Serverless PostgreSQL for Movements+ & FitTrack.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# ==============================================================================
# CORS MIDDLEWARE (Enabled for Expo, React Native, physical devices & emulators)
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Unrestricted access for mobile clients & dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# REGISTER ROUTERS
# ==============================================================================
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(dashboard.router, prefix=settings.API_V1_STR)
app.include_router(vitals.router, prefix=settings.API_V1_STR)
app.include_router(nutrition.router, prefix=settings.API_V1_STR)
app.include_router(workouts.router, prefix=settings.API_V1_STR)
app.include_router(history.router, prefix=settings.API_V1_STR)
app.include_router(ai.router, prefix=settings.API_V1_STR)
app.include_router(sleep.router, prefix=settings.API_V1_STR)
app.include_router(masturbation.router, prefix=settings.API_V1_STR)
app.include_router(cycle.router, prefix=settings.API_V1_STR)


# ==============================================================================
# DATABASE INITIALIZATION & HEALTH
# ==============================================================================
def _db_kind() -> str:
    return "SQLite (local file)" if settings.is_sqlite else "PostgreSQL (NeonDB)"


@app.api_route(f"{settings.API_V1_STR}/init-db", methods=["GET", "POST"], tags=["Database Initialization"])
async def init_database():
    """Creates any missing tables (safe to call repeatedly; never deletes data)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(add_missing_columns)
    return {
        "status": "success",
        "database_type": _db_kind(),
        "tables": sorted(Base.metadata.tables.keys()),
    }


if not _is_hosted:
    # Local development only: resets the demo account with sample data.
    @app.post(f"{settings.API_V1_STR}/seed-demo", tags=["Demo & Seeding"])
    async def trigger_seed_demo(db: AsyncSession = Depends(get_db)):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return await seed_demo_data(db)


@app.get("/ping", tags=["Health"])
async def ping():
    """Lightweight check for keep-alive pings and uptime monitors (no database query)."""
    return {"ok": True}


@app.get("/health", tags=["Health"])
async def health_check():
    """Verifies the API and the database connection."""
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "healthy" if db_ok else "degraded",
        "service": settings.PROJECT_NAME,
        "database": _db_kind(),
        "database_connected": db_ok,
        "google_sign_in_configured": settings.google_oauth_enabled,
        "ai_assistant_configured": settings.ai_enabled,
        "cors_origins": ["*"],
        "version": "1.4.0",
    }
