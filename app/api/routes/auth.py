from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.activity import DailyVitals
from app.models.heart_rate import SleepZoneBenchmarks
from app.models.nutrition import NutritionLog
from app.models.user import User
from app.schemas.auth import TokenResponse, UserGoogleLogin, UserLogin, UserOnboardingUpdate, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication & Onboarding (Screens 1 & 2)"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    """Registers a new user, hashes password, and returns JWT token (Screen 1)."""
    email_clean = payload.email.lower().strip()
    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists.",
        )

    # Calculate default target heart rate: round((220 - 24) * 0.7) = 137
    user = User(
        email=email_clean,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        avatar_url=payload.avatar_url,
        is_active=True,
        is_onboarded=False,
        age=24,
        weight_kg=72.2,
        height_cm=176.0,
        primary_goal="Fat Burn",
        target_hr_bpm=137,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token, token_type="bearer", user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Logs in an existing user with email and password (Screen 1)."""
    email_clean = payload.email.lower().strip()
    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    # Pre-seed demo user automatically if demo credentials are used
    if user is None and email_clean == "ragul@fittrack.io":
        user = User(
            email="ragul@fittrack.io",
            hashed_password=get_password_hash("password123"),
            full_name="Jonathan Sanders",
            avatar_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100",
            is_active=True,
            is_onboarded=True,
            age=24,
            weight_kg=72.2,
            height_cm=176.0,
            primary_goal="Fat Burn",
            target_hr_bpm=137,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token, token_type="bearer", user=UserRead.model_validate(user))


@router.post("/google", response_model=TokenResponse)
async def google_login(payload: UserGoogleLogin, db: AsyncSession = Depends(get_db)):
    """Authenticates or registers a user via Google OAuth (Screen 1)."""
    import uuid
    email_clean = payload.email.lower().strip()
    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=email_clean,
            hashed_password=get_password_hash(f"google_{uuid.uuid4().hex[:12]}"),
            full_name=payload.full_name or "Google Athlete",
            avatar_url=payload.avatar_url or "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100",
            is_active=True,
            is_onboarded=False,
            age=24,
            weight_kg=72.2,
            height_cm=176.0,
            primary_goal="Fat Burn",
            target_hr_bpm=137,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated",
            )
        if payload.avatar_url and not user.avatar_url:
            user.avatar_url = payload.avatar_url
            await db.commit()
            await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token, token_type="bearer", user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Returns the authenticated user's profile and biometrics."""
    return UserRead.model_validate(current_user)


@router.put("/onboarding", response_model=UserRead)
async def update_onboarding_biometrics(
    payload: UserOnboardingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calibrates age, weight, height, goal, and auto-calculates Target Heart Rate (Screen 2)."""
    current_user.age = payload.age
    current_user.weight_kg = payload.weight_kg
    current_user.height_cm = payload.height_cm
    current_user.primary_goal = payload.primary_goal

    # Formula: target_hr_bpm = round((220 - age) * 0.70)
    calculated_hr = payload.target_hr_bpm or round((220 - payload.age) * 0.70)
    current_user.target_hr_bpm = calculated_hr
    current_user.is_onboarded = True

    today = datetime.now(timezone.utc).date()

    # Ensure baseline daily vitals exist for today
    vitals_stmt = select(DailyVitals).where(
        DailyVitals.user_id == current_user.id,
        DailyVitals.date == today,
    )
    vitals_res = await db.execute(vitals_stmt)
    if not vitals_res.scalar_one_or_none():
        vitals = DailyVitals(
            user_id=current_user.id,
            date=today,
            agenda_title="Walking",
            steps_count=7435,
            weight_kg=payload.weight_kg,
            weight_status="Stable Weight",
            latest_hr_bpm=101,
            hr_status="High HR",
            body_composition_pct=87.9,
            body_comp_badge="Gaining Muscle",
        )
        db.add(vitals)

    # Ensure baseline sleep benchmarks exist
    bench_stmt = select(SleepZoneBenchmarks).where(
        SleepZoneBenchmarks.user_id == current_user.id,
        SleepZoneBenchmarks.recorded_date == today,
    )
    bench_res = await db.execute(bench_stmt)
    if not bench_res.scalar_one_or_none():
        bench = SleepZoneBenchmarks(
            user_id=current_user.id,
            recorded_date=today,
            light_pct="40-60%",
            rem_pct="15-25%",
            deep_pct="8-16%",
            awake_pct="12-24%",
        )
        db.add(bench)

    # Ensure baseline nutrition log exists
    nutr_stmt = select(NutritionLog).where(
        NutritionLog.user_id == current_user.id,
        NutritionLog.date == today,
    )
    nutr_res = await db.execute(nutr_stmt)
    if not nutr_res.scalar_one_or_none():
        nutr = NutritionLog(
            user_id=current_user.id,
            date=today,
            calories_consumed=1840,
            calories_goal=2400,
            protein_g=142,
            carbs_g=210,
            fats_g=58,
            water_liters=2.5,
            water_goal_liters=3.0,
            metabolic_score_pct=92,
        )
        db.add(nutr)

    await db.commit()
    await db.refresh(current_user)
    return UserRead.model_validate(current_user)
