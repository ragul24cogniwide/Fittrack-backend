import json
import os
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Development-only default; it is public in the repository, so hosted
# deployments must set their own JWT_SECRET (see guard at the bottom).
_DEV_JWT_SECRET = "fittrack_local_development_only_secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Movements+ & FitTrack API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # NeonDB Serverless PostgreSQL connection URL (Async asyncpg driver)
    DATABASE_URL: str = "sqlite+aiosqlite:///./fittrack_local.db"

    # JWT Authentication
    JWT_SECRET: str = _DEV_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS settings
    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    # Google OAuth (Web application client from Google Cloud Console).
    # The backend runs the OAuth code flow so the mobile app never sees the secret.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # Also ask Google for the account's gender (People API, "user.gender.read").
    # It's a sensitive scope: Google shows an "unverified app" notice until the
    # OAuth consent screen is verified. Set to false to stop asking.
    GOOGLE_REQUEST_GENDER: bool = True
    # Public https URL of this backend, e.g. https://fittrack-backend-nqkx.onrender.com
    # Used to build the Google redirect URI: {PUBLIC_BASE_URL}{API_V1_STR}/auth/google/callback
    PUBLIC_BASE_URL: str = ""
    # Render's free plan sleeps after ~15 min without requests. While hosted, the server pings its own
    # public /ping every KEEP_ALIVE_SECONDS so it stays awake (0 = off). /ping doesn't touch the database,
    # so NeonDB can still pause when nobody uses the app.
    KEEP_ALIVE_SECONDS: int = 30
    # Deep link the app listens on after Google sign-in completes
    APP_DEEP_LINK: str = "fittrack://auth/google"

    # AI food & activity logging (Google Gemini API, key from aistudio.google.com).
    # Without a key the AI chat endpoint answers 503 and the rest of the app works.
    GEMINI_API_KEY: str = ""
    AI_MODEL: str = "gemini-3.5-flash-lite"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v: Union[bool, str]) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("true", "1", "t", "yes", "debug"):
                return True
            return False
        return bool(v)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if not v:
            return "sqlite+aiosqlite:///./fittrack_local.db"
        # Neon dashboard copies provide postgresql:// or postgres://
        # Convert to asyncpg dialect for SQLAlchemy 2.0 Async
        url = v.strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg prefers ssl=require over sslmode=require
        if "sslmode=require" in url:
            url = url.replace("sslmode=require", "ssl=require")
        return url

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v_strip = v.strip()
            if v_strip.startswith("[") and v_strip.endswith("]"):
                try:
                    return json.loads(v_strip)
                except Exception:
                    pass
            return [i.strip() for i in v_strip.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["*"]


settings = Settings()

_is_hosted = settings.ENVIRONMENT.lower() == "production" or os.environ.get("RENDER") == "true"
if _is_hosted and settings.is_sqlite:
    # Fail loudly: silently falling back to an ephemeral SQLite file on the
    # server means every redeploy/restart wipes all user accounts.
    raise RuntimeError(
        "DATABASE_URL is not set. Set it to your NeonDB connection string "
        "in the hosting provider's environment variables."
    )
if _is_hosted and settings.JWT_SECRET == _DEV_JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET is not set. Generate one with "
        "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
        "and add it to the hosting provider's environment variables."
    )

