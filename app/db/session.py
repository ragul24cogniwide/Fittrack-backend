import ssl
from typing import Any, AsyncGenerator, Dict, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def normalize_neon_database_url(raw_url: str) -> Tuple[str, Dict[str, Any]]:
    """
    Automatically converts standard Neon connection strings:
    - Converts postgresql:// or postgres:// to postgresql+asyncpg://
    - Handles sslmode=require cleanly for asyncpg by removing conflicting query
      params and configuring a secure SSL context in connect_args.
    - Sets statement_cache_size=0 for Neon serverless PgBouncer poolers.
    """
    if not raw_url:
        return "sqlite+aiosqlite:///./fittrack_local.db", {}

    url = raw_url.strip()
    connect_args: Dict[str, Any] = {}

    # 1. Scheme conversion for SQLAlchemy 2.0 Async (asyncpg dialect)
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    # 2. Parse query parameters and clean sslmode for asyncpg
    parsed = urlparse(url)
    is_postgres = parsed.scheme.startswith("postgresql")

    if is_postgres:
        query_params = parse_qs(parsed.query)
        needs_ssl = (
            "neon.tech" in parsed.netloc
            or "sslmode" in query_params
            or "ssl" in query_params
        )

        # asyncpg does not accept 'sslmode' in query params; strip to prevent crashes
        query_params.pop("sslmode", None)
        query_params.pop("ssl", None)

        # Reconstruct clean database URL
        new_query = urlencode(query_params, doseq=True)
        url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))

        # 3. Configure SSL context and statement cache for NeonDB
        if needs_ssl:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_ctx
            # Neon serverless PgBouncer connection pooling requirement
            connect_args["statement_cache_size"] = 0

    return url, connect_args


# Build clean NeonDB URL and connect arguments
db_url, extra_connect_args = normalize_neon_database_url(settings.DATABASE_URL)

engine_kwargs: Dict[str, Any] = {
    "echo": settings.DEBUG and settings.ENVIRONMENT == "development",
    "pool_pre_ping": True,  # Discards stale serverless connections before checkout
    "pool_recycle": 300,   # 300s (5 min) recycle for Neon scale-to-zero cold starts
}

if extra_connect_args:
    engine_kwargs["connect_args"] = extra_connect_args

if db_url.startswith("postgresql"):
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

# Create async engine tailored for NeonDB Serverless PostgreSQL
engine = create_async_engine(db_url, **engine_kwargs)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
