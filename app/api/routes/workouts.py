from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.activity import WorkoutSession
from app.models.user import User
from app.schemas.activity import (
    WorkoutSessionCreate,
    WorkoutSessionRead,
    WorkoutSessionUpdate,
    WorkoutTickRequest,
)

router = APIRouter(prefix="/workouts", tags=["Active Workout Session (Screens 3 & 7)"])


@router.get("/active", response_model=Optional[WorkoutSessionRead])
async def get_active_workout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves current in-progress or paused workout session (Screen 7)."""
    stmt = (
        select(WorkoutSession)
        .where(
            WorkoutSession.user_id == current_user.id,
            WorkoutSession.status.in_(["in_progress", "paused"]),
        )
        .order_by(WorkoutSession.id.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    workout = res.scalars().first()
    if workout:
        return WorkoutSessionRead.model_validate(workout)
    return None


@router.post("/start", response_model=WorkoutSessionRead, status_code=status.HTTP_201_CREATED)
async def start_or_resume_workout(
    payload: WorkoutSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Starts or resumes a workout session (Running or Skateboard) (Screen 7)."""
    # Check if an existing in_progress session matches
    stmt = select(WorkoutSession).where(
        WorkoutSession.user_id == current_user.id,
        WorkoutSession.title == payload.title,
        WorkoutSession.status.in_(["in_progress", "paused"]),
    ).order_by(WorkoutSession.id.desc()).limit(1)
    res = await db.execute(stmt)
    existing_workout = res.scalars().first()

    if existing_workout:
        existing_workout.status = "in_progress"
        await db.commit()
        await db.refresh(existing_workout)
        return WorkoutSessionRead.model_validate(existing_workout)

    # Start new session
    workout = WorkoutSession(
        user_id=current_user.id,
        title=payload.title,
        category=payload.category,
        status="in_progress",
        progress_pct=0,
        duration_seconds=0,
        target_duration_seconds=payload.target_duration_seconds,
        distance_km=payload.distance_km,
        pace_str="--",
        calories_burned=0,
        avg_hr_bpm=0,
    )
    db.add(workout)
    await db.commit()
    await db.refresh(workout)
    return WorkoutSessionRead.model_validate(workout)


@router.patch("/{workout_id}/tick", response_model=WorkoutSessionRead)
@router.put("/{workout_id}/update", response_model=WorkoutSessionRead, include_in_schema=False)
async def update_workout_tick(
    workout_id: int,
    payload: WorkoutTickRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates live elapsed duration, distance, live BPM, and progress_pct."""
    stmt = select(WorkoutSession).where(
        WorkoutSession.id == workout_id,
        WorkoutSession.user_id == current_user.id,
    )
    res = await db.execute(stmt)
    workout = res.scalar_one_or_none()

    if not workout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workout not found")

    if workout.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workout already completed")

    if payload.duration_seconds is not None:
        workout.duration_seconds = payload.duration_seconds
        if payload.progress_pct is None:
            workout.progress_pct = min(
                100, round(payload.duration_seconds * 100 / max(1, workout.target_duration_seconds))
            )
    if payload.distance_km is not None:
        workout.distance_km = payload.distance_km
    if payload.live_bpm is not None:
        workout.avg_hr_bpm = payload.live_bpm
    if payload.progress_pct is not None:
        workout.progress_pct = payload.progress_pct
    if payload.calories_burned is not None:
        workout.calories_burned = payload.calories_burned
    if payload.pace_str is not None:
        workout.pace_str = payload.pace_str
    if payload.steps_count is not None:
        workout.steps_count = payload.steps_count
    if payload.status is not None:
        workout.status = payload.status

    await db.commit()
    await db.refresh(workout)
    return WorkoutSessionRead.model_validate(workout)


@router.post("/{workout_id}/complete", response_model=WorkoutSessionRead)
@router.post("/{workout_id}/finish", response_model=WorkoutSessionRead, include_in_schema=False)
async def complete_workout(
    workout_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marks session completed and increments user's Workout Progress Total Time."""
    stmt = select(WorkoutSession).where(
        WorkoutSession.id == workout_id,
        WorkoutSession.user_id == current_user.id,
    )
    res = await db.execute(stmt)
    workout = res.scalar_one_or_none()

    if not workout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workout not found")

    # Steps are already counted into daily vitals by the phone's step sensor,
    # so completing a workout must not add them a second time.
    workout.status = "completed"

    await db.commit()
    await db.refresh(workout)
    return WorkoutSessionRead.model_validate(workout)


@router.get("", response_model=List[WorkoutSessionRead])
async def list_workouts(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists recent workout history."""
    stmt = (
        select(WorkoutSession)
        .where(WorkoutSession.user_id == current_user.id)
        .order_by(WorkoutSession.id.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return [WorkoutSessionRead.model_validate(w) for w in res.scalars().all()]
