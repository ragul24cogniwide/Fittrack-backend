from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today, get_or_create_daily, week_start
from app.api.deps import get_current_user, get_db
from app.models.activity import DailyVitals, WorkoutSession
from app.models.nutrition import NutritionLog
from app.models.user import User
from app.schemas.dashboard import (
    ActivityCardSummary,
    DashboardResponse,
    NutrientsSummaryBar,
)

router = APIRouter(prefix="/dashboard", tags=["Home Dashboard (Screen 3)"])

# WHO guideline: 150 minutes of moderate activity per week
WEEKLY_GOAL_MINUTES = 150
# The two activity cards shown on the home screen
HOME_ACTIVITIES = [("Running", "Sports"), ("Skateboard", "Sports")]


def _card_for(title: str, category: str, w: Optional[WorkoutSession]) -> ActivityCardSummary:
    if w is None:
        return ActivityCardSummary(title=title, category=category)
    active = w.status in ("in_progress", "paused")
    return ActivityCardSummary(
        id=w.id,
        title=w.title,
        category=w.category,
        status=w.status,
        progress_pct=w.progress_pct,
        distance_km=round(w.distance_km, 2),
        duration_minutes=w.duration_seconds // 60,
        calories_burned=w.calories_burned,
        action_label="Continue" if active else "Start",
    )


@router.get("/today", response_model=DashboardResponse)
@router.get("/overview", response_model=DashboardResponse, include_in_schema=False)
async def get_today_dashboard(
    category: Optional[str] = Query(
        None,
        description="Filter activity cards by category: 'All', 'Meditation', 'Sports', 'Mindfulness'",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
    x_tz_offset_minutes: Optional[int] = Header(None),
):
    """Returns the live payload for Screen 3 ('Today, FitTrack+')."""
    # Start of this week (Monday 00:00 on the device) expressed in UTC
    offset = timedelta(minutes=x_tz_offset_minutes or 0)
    week_start_utc = (
        datetime.combine(week_start(today), time.min, tzinfo=timezone.utc) + offset
    )

    community = (await db.execute(select(func.count(User.id)))).scalar_one()

    week_seconds, week_completed = (
        await db.execute(
            select(
                func.coalesce(func.sum(WorkoutSession.duration_seconds), 0),
                func.count(WorkoutSession.id).filter(WorkoutSession.status == "completed"),
            ).where(
                WorkoutSession.user_id == current_user.id,
                WorkoutSession.created_at >= week_start_utc,
            )
        )
    ).one()

    total_calories = (
        await db.execute(
            select(func.coalesce(func.sum(WorkoutSession.calories_burned), 0)).where(
                WorkoutSession.user_id == current_user.id
            )
        )
    ).scalar_one()

    # Latest session per home activity
    cards = []
    for title, cat in HOME_ACTIVITIES:
        if category and category.lower() not in ("all", cat.lower()):
            continue
        latest = (
            await db.execute(
                select(WorkoutSession)
                .where(WorkoutSession.user_id == current_user.id, WorkoutSession.title == title)
                .order_by(WorkoutSession.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        cards.append(_card_for(title, cat, latest))

    vitals = await get_or_create_daily(db, DailyVitals, current_user, today)
    nutr = await get_or_create_daily(db, NutritionLog, current_user, today)

    week_minutes = int(week_seconds) // 60
    return DashboardResponse(
        user_name=current_user.full_name,
        avatar_url=current_user.avatar_url,
        community_joined_count=community,
        workout_minutes_week=week_minutes,
        workout_goal_minutes_week=WEEKLY_GOAL_MINUTES,
        workout_progress_hours=f"{week_minutes / 60:.1f}/{WEEKLY_GOAL_MINUTES / 60:g}H",
        workout_progress_pct=min(100, round(week_minutes * 100 / WEEKLY_GOAL_MINUTES)),
        workouts_completed_week=int(week_completed),
        total_calories_burned=int(total_calories),
        steps_today=vitals.steps_count,
        activity_cards=cards,
        nutrients_summary=NutrientsSummaryBar(
            calories_consumed=nutr.calories_consumed,
            calories_goal=nutr.calories_goal,
            percentage=round(nutr.calories_consumed * 100 / max(1, nutr.calories_goal)),
            protein_g=nutr.protein_g,
            carbs_g=nutr.carbs_g,
            fats_g=nutr.fats_g,
        ),
    )
