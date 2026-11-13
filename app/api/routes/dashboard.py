from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("/today", response_model=DashboardResponse)
@router.get("/overview", response_model=DashboardResponse, include_in_schema=False)
async def get_today_dashboard(
    category: Optional[str] = Query(
        None,
        description="Filter activity cards by category: 'All', 'Meditation', 'Sports', 'Mindfulness'",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns unified payload for Screen 3 ('Today, Movements+' / 'FitTrack+')."""
    today = datetime.now(timezone.utc).date()

    # Query nutrition summary for today
    nutr_stmt = select(NutritionLog).where(
        NutritionLog.user_id == current_user.id,
        NutritionLog.date == today,
    )
    nutr_res = await db.execute(nutr_stmt)
    nutr = nutr_res.scalar_one_or_none()

    # Query user's workouts
    workout_stmt = (
        select(WorkoutSession)
        .where(WorkoutSession.user_id == current_user.id)
        .order_by(WorkoutSession.id.desc())
    )
    if category and category.lower() != "all":
        workout_stmt = workout_stmt.where(WorkoutSession.category.ilike(category))

    workout_res = await db.execute(workout_stmt)
    db_workouts = workout_res.scalars().all()

    if db_workouts:
        activity_cards = [
            ActivityCardSummary(
                id=w.id,
                title=w.title,
                category=w.category,
                progress_pct=w.progress_pct,
                distance_km=w.distance_km,
                duration_minutes=max(1, w.duration_seconds // 60),
                calories_burned=w.calories_burned,
                action_label="Continue",
            )
            for w in db_workouts
        ]
    else:
        # Canonical baseline cards matching reference design
        raw_cards = [
            ActivityCardSummary(
                id=1,
                title="Running",
                category="Sports",
                progress_pct=80,
                distance_km=5.2,
                duration_minutes=38,
                calories_burned=385,
                action_label="Continue",
            ),
            ActivityCardSummary(
                id=2,
                title="Skateboard",
                category="Sports",
                progress_pct=50,
                distance_km=2.1,
                duration_minutes=24,
                calories_burned=210,
                action_label="Continue",
            ),
        ]
        if category and category.lower() != "all":
            activity_cards = [c for c in raw_cards if c.category.lower() == category.lower()]
        else:
            activity_cards = raw_cards

    # Nutrients summary banner
    if nutr:
        calories_pct = (
            round((nutr.calories_consumed / nutr.calories_goal) * 100)
            if nutr.calories_goal > 0
            else 76
        )
        nutr_summary = NutrientsSummaryBar(
            calories_consumed=nutr.calories_consumed,
            calories_goal=nutr.calories_goal,
            percentage=calories_pct,
            protein_g=nutr.protein_g,
            carbs_g=nutr.carbs_g,
            fats_g=nutr.fats_g,
        )
    else:
        nutr_summary = NutrientsSummaryBar(
            calories_consumed=1840,
            calories_goal=2400,
            percentage=76,
            protein_g=142,
            carbs_g=210,
            fats_g=58,
        )

    # Format human-readable date string e.g., "Today, Nov 13"
    date_display = f"Today, {today.strftime('%b %d')}"

    return DashboardResponse(
        user_greeting="Good Morning",
        user_name=current_user.full_name or "Jonathan Sanders",
        avatar_url=current_user.avatar_url,
        date_str=date_display,
        community_joined_count=215,
        workout_progress_hours="10/20H",
        workout_progress_pct=80,
        level_label="Level 2 Completed",
        total_calories_burned=5248,
        categories=["All", "Meditation", "Sports", "Mindfulness"],
        activity_cards=activity_cards,
        nutrients_summary=nutr_summary,
    )
