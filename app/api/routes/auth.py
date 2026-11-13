import html
import secrets
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt as jose_jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today
from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.models.activity import DailyVitals
from app.models.user import User
from app.schemas.auth import (
    TokenResponse,
    UserGoogleLogin,
    UserLogin,
    UserOnboardingUpdate,
    UserRead,
    UserRegister,
)

router = APIRouter(prefix="/auth", tags=["Authentication & Onboarding (Screens 1 & 2)"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


def _token_response(user: User) -> TokenResponse:
    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token, token_type="bearer", user=UserRead.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    """Registers a new user, hashes password, and returns JWT token (Screen 1)."""
    email_clean = payload.email.lower().strip()
    existing = await db.execute(select(User).where(User.email == email_clean))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists. Please sign in.",
        )

    user = User(
        email=email_clean,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name.strip() or "Athlete",
        avatar_url=payload.avatar_url,
        is_active=True,
        is_onboarded=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Logs in an existing user with email and password (Screen 1)."""
    email_clean = payload.email.lower().strip()
    user = (await db.execute(select(User).where(User.email == email_clean))).scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    return _token_response(user)


# ==============================================================================
# GOOGLE SIGN-IN
# ==============================================================================
async def _upsert_google_user(
    db: AsyncSession, email: str, full_name: Optional[str], avatar_url: Optional[str]
) -> User:
    email_clean = email.lower().strip()
    user = (await db.execute(select(User).where(User.email == email_clean))).scalar_one_or_none()

    if user is None:
        user = User(
            email=email_clean,
            # Random unusable password: Google accounts sign in via Google only
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            full_name=(full_name or email_clean.split("@")[0])[:100],
            avatar_url=avatar_url,
            is_active=True,
            is_onboarded=False,
        )
        db.add(user)
    else:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
    await db.commit()
    await db.refresh(user)
    return user


def _google_redirect_uri(request: Request) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}{settings.API_V1_STR}/auth/google/callback"


def _deep_link_page(params: dict) -> HTMLResponse:
    """
    Hands the result back to the app. Chrome only follows custom-scheme links
    reliably from a page, so render one that redirects and offers a button.
    """
    link = f"{settings.APP_DEEP_LINK}?{urlencode(params)}"
    safe = html.escape(link, quote=True)
    ok = "token" in params
    body = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0;url={safe}"><title>FitTrack</title>
<style>body{{font-family:sans-serif;background:#121A19;color:#fff;display:flex;
flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0;gap:20px}}
a{{background:#D4F872;color:#121A19;padding:14px 28px;border-radius:999px;
text-decoration:none;font-weight:700}}</style></head><body>
<p>{"Signed in. Returning to FitTrack..." if ok else "Google sign-in failed."}</p>
<a href="{safe}">Open FitTrack</a>
<script>window.location.replace({link!r});</script></body></html>"""
    return HTMLResponse(body)


@router.get("/google/start", include_in_schema=True)
async def google_start(request: Request, app_state: str = ""):
    """
    Step 1 of Google sign-in. The app opens this URL in Chrome; we redirect to
    Google's account chooser using the server-side Web OAuth client.
    """
    if not settings.google_oauth_enabled:
        return _deep_link_page({"error": "google_not_configured", "app_state": app_state})

    state = create_access_token(
        subject="google_oauth",
        expires_delta=timedelta(minutes=10),
        extra_claims={"purpose": "google_oauth", "app_state": app_state[:128]},
    )
    query = urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": _google_redirect_uri(request),
            "response_type": "code",
            "scope": "openid email profile",
            "prompt": "select_account",
            "state": state,
        }
    )
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}", status_code=302)


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Step 2: Google redirects here with a one-time code; exchange it and sign in."""
    claims = decode_access_token(state or "") or {}
    app_state = claims.get("app_state", "")
    if claims.get("purpose") != "google_oauth":
        return _deep_link_page({"error": "invalid_state", "app_state": app_state})
    if error or not code:
        return _deep_link_page({"error": error or "missing_code", "app_state": app_state})

    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _google_redirect_uri(request),
                "grant_type": "authorization_code",
            },
        )
    if token_res.status_code != 200:
        return _deep_link_page({"error": "token_exchange_failed", "app_state": app_state})

    # The ID token came straight from Google's token endpoint over TLS, so its
    # claims can be trusted without re-verifying the signature (OIDC Core 3.1.3.7).
    id_claims = jose_jwt.get_unverified_claims(token_res.json().get("id_token", ""))
    if (
        id_claims.get("aud") != settings.GOOGLE_CLIENT_ID
        or id_claims.get("iss") not in GOOGLE_ISSUERS
        or not id_claims.get("email")
        or not id_claims.get("email_verified")
    ):
        return _deep_link_page({"error": "unverified_google_account", "app_state": app_state})

    user = await _upsert_google_user(
        db, id_claims["email"], id_claims.get("name"), id_claims.get("picture")
    )
    return _deep_link_page(
        {"token": create_access_token(subject=str(user.id)), "app_state": app_state}
    )


@router.post("/google", response_model=TokenResponse)
async def google_login(payload: UserGoogleLogin, db: AsyncSession = Depends(get_db)):
    """
    Signs in with a Google ID token obtained natively on the device.
    The token is verified with Google; the email in the body is never trusted.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in is not configured")
    if not payload.id_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "id_token is required")

    async with httpx.AsyncClient(timeout=15) as client:
        info_res = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": payload.id_token})
    info = info_res.json() if info_res.status_code == 200 else {}
    if (
        info.get("aud") != settings.GOOGLE_CLIENT_ID
        or info.get("iss") not in GOOGLE_ISSUERS
        or info.get("email_verified") not in ("true", True)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google ID token")

    user = await _upsert_google_user(db, info["email"], info.get("name"), info.get("picture"))
    return _token_response(user)


# ==============================================================================
# PROFILE & ONBOARDING
# ==============================================================================
@router.get("/me", response_model=UserRead)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Returns the authenticated user's profile and biometrics."""
    return UserRead.model_validate(current_user)


@router.put("/onboarding", response_model=UserRead)
async def update_onboarding_biometrics(
    payload: UserOnboardingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Calibrates age, weight, height, goal, and auto-calculates Target Heart Rate (Screen 2)."""
    current_user.age = payload.age
    current_user.weight_kg = payload.weight_kg
    current_user.height_cm = payload.height_cm
    current_user.primary_goal = payload.primary_goal
    # Formula: target_hr_bpm = round((220 - age) * 0.70)
    current_user.target_hr_bpm = payload.target_hr_bpm or round((220 - payload.age) * 0.70)
    current_user.is_onboarded = True

    # Keep today's weight reading in sync if the day's row already exists
    vitals = (
        await db.execute(
            select(DailyVitals).where(
                DailyVitals.user_id == current_user.id, DailyVitals.date == today
            )
        )
    ).scalar_one_or_none()
    if vitals:
        vitals.weight_kg = payload.weight_kg

    await db.commit()
    await db.refresh(current_user)
    return UserRead.model_validate(current_user)
