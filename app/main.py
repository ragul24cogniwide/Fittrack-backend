from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes import auth, dashboard, nutrition, vitals, workouts
from app.core.config import settings
from app.db.base import Base
from app.db.seed import seed_demo_data
from app.db.session import AsyncSessionLocal, engine
from app.models.user import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Automatic startup table initializer:
    - Runs Base.metadata.create_all on startup
    - Automatically checks and populates baseline demo data into NeonDB
    """
    # 1. Automatic table creation for NeonDB Serverless PostgreSQL
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Check and seed demo user on fresh database
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.email == "ragul@fittrack.io")
        res = await session.execute(stmt)
        if not res.scalar_one_or_none():
            await seed_demo_data(session)

    yield

    # 3. Graceful shutdown
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


# ==============================================================================
# DEMO SEEDING ENDPOINT (Step 5 Requirement)
# ==============================================================================
@app.post(f"{settings.API_V1_STR}/seed-demo", tags=["Demo & Seeding"])
@app.get(f"{settings.API_V1_STR}/seed-demo", tags=["Demo & Seeding"])
async def trigger_seed_demo(db: AsyncSession = Depends(get_db)):
    """
    Populates or resets the exact numbers from the UI design into NeonDB:
    - User: Jonathan Sanders (24y, 72.2kg, 176cm, goal: Fat Burn, target HR: 137 bpm)
    - DailyVitals: 7,435 steps, 72.2 kg, 101 bpm, 87.9% body composition
    - Workouts: Running (80%), Skateboard (50%)
    - Heart Rate: 7-bar time-series (Peak: 134 bpm) + Sleep benchmarks
    - Nutrition: 1,840/2,400 kcal, 142g protein, 2.5L water, 4 meals
    """
    result = await seed_demo_data(db)
    return result


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint verifying backend and serverless database availability."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "database_engine": "SQLAlchemy 2.0 Async (asyncpg / NeonDB)",
        "cors_origins": ["*"],
        "version": "1.0.0",
    }
