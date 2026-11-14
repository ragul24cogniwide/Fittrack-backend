"""History: per-day records of steps, weight, nutrition, workouts and heart rate."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today
from app.api.deps import get_current_user, get_db
from app.models.activity import DailyVitals, WorkoutSession
from app.models.heart_rate import HeartRateAnalytics
from app.models.nutrition import MealEntry, NutritionLog
from app.models.user import User
from app.schemas.activity import WorkoutSessionRead
from app.schemas.heart_rate import HeartRateAnalyticsRead
from app.schemas.history import DayDetail, DayHistory, HistorySummary, HistoryTotals
from app.schemas.nutrition import MealEntryRead

router = APIRouter(prefix="/history", tags=["History"])

STEP_GOAL = 10000


def _offset(x_tz_offset_minutes: Optional[int]) -> timedelta:
    if x_tz_offset_minutes is None or not -840 <= x_tz_offset_minutes <= 840:
        return timedelta(0)
    return timedelta(minutes=x_tz_offset_minutes)


def _day_bounds_utc(start: date, end: date, offset: timedelta):
    """UTC instants covering device-local days start..end inclusive."""
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc) + offset
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc) + offset
    return lo, hi


def _local_date(ts: datetime, offset: timedelta) -> date:
    if ts.tzinfo is None:  # SQLite returns naive UTC
        ts = ts.replace(tzinfo=timezone.utc)
    return (ts - offset).date()


async def _build_days(
    db: AsyncSession, user: User, start: date, end: date, offset: timedelta
) -> Dict[date, DayHistory]:
    days: Dict[date, DayHistory] = {}
    d = start
    while d <= end:
        days[d] = DayHistory(date=d)
        d += timedelta(days=1)

    stride_km = user.height_cm * 0.415 / 100000  # average walking step length

    for v in (
        await db.execute(
            select(DailyVitals).where(
                DailyVitals.user_id == user.id, DailyVitals.date.between(start, end)
            )
        )
    ).scalars():
        day = days[v.date]
        day.steps_count = v.steps_count
        day.distance_km = round(v.steps_count * stride_km, 2)
        day.weight_kg = v.weight_kg

    for n in (
        await db.execute(
            select(NutritionLog).where(
                NutritionLog.user_id == user.id, NutritionLog.date.between(start, end)
            )
        )
    ).scalars():
        day = days[n.date]
        day.calories_consumed = n.calories_consumed
        day.protein_g = n.protein_g
        day.water_liters = n.water_liters

    lo, hi = _day_bounds_utc(start, end, offset)
    for w in (
        await db.execute(
            select(WorkoutSession).where(
                WorkoutSession.user_id == user.id,
                WorkoutSession.created_at >= lo,
                WorkoutSession.created_at < hi,
            )
        )
    ).scalars():
        day = days.get(_local_date(w.created_at, offset))
        if day:
            day.workouts += 1
            day.workout_minutes += w.duration_seconds // 60
            day.workout_calories += w.calories_burned

    for rec_date, count, avg in (
        await db.execute(
            select(
                HeartRateAnalytics.recorded_date,
                func.count(HeartRateAnalytics.id),
                func.avg(HeartRateAnalytics.bpm_value),
            )
            .where(
                HeartRateAnalytics.user_id == user.id,
                HeartRateAnalytics.recorded_date.between(start, end),
            )
            .group_by(HeartRateAnalytics.recorded_date)
        )
    ).all():
        days[rec_date].hr_readings = int(count)
        days[rec_date].avg_hr_bpm = round(float(avg))

    return days


@router.get("/summary", response_model=HistorySummary)
async def get_history_summary(
    days: int = Query(7, ge=1, le=365, description="Number of days ending today"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
    x_tz_offset_minutes: Optional[int] = Header(None),
):
    """Day-by-day history for the last `days` days (oldest first), plus totals."""
    start = today - timedelta(days=days - 1)
    by_day = await _build_days(db, current_user, start, today, _offset(x_tz_offset_minutes))
    rows: List[DayHistory] = list(by_day.values())

    total_steps = sum(r.steps_count for r in rows)
    best = max(rows, key=lambda r: r.steps_count)
    meal_days = [r for r in rows if r.calories_consumed > 0]
    totals = HistoryTotals(
        steps=total_steps,
        avg_steps_per_day=round(total_steps / len(rows)),
        best_steps_day=best.date if best.steps_count > 0 else None,
        best_steps=best.steps_count,
        days_step_goal_met=sum(1 for r in rows if r.steps_count >= STEP_GOAL),
        distance_km=round(sum(r.distance_km for r in rows), 2),
        workouts=sum(r.workouts for r in rows),
        workout_minutes=sum(r.workout_minutes for r in rows),
        workout_calories=sum(r.workout_calories for r in rows),
        avg_calories_consumed=(
            round(sum(r.calories_consumed for r in meal_days) / len(meal_days)) if meal_days else 0
        ),
    )
    return HistorySummary(
        start_date=start, end_date=today, step_goal=STEP_GOAL, days=rows, totals=totals
    )


@router.get("/day/{day}", response_model=DayDetail)
async def get_day_detail(
    day: date,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
    x_tz_offset_minutes: Optional[int] = Header(None),
):
    """Everything recorded on one day: meals, workouts and heart-rate readings."""
    if day > today:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Date is in the future")
    offset = _offset(x_tz_offset_minutes)
    summary = (await _build_days(db, current_user, day, day, offset))[day]

    meals = (
        await db.execute(
            select(MealEntry)
            .join(NutritionLog, MealEntry.nutrition_log_id == NutritionLog.id)
            .where(MealEntry.user_id == current_user.id, NutritionLog.date == day)
            .order_by(MealEntry.logged_at)
        )
    ).scalars().all()

    lo, hi = _day_bounds_utc(day, day, offset)
    workouts = (
        await db.execute(
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == current_user.id,
                WorkoutSession.created_at >= lo,
                WorkoutSession.created_at < hi,
            )
            .order_by(WorkoutSession.created_at)
        )
    ).scalars().all()

    readings = (
        await db.execute(
            select(HeartRateAnalytics)
            .where(
                HeartRateAnalytics.user_id == current_user.id,
                HeartRateAnalytics.recorded_date == day,
            )
            .order_by(HeartRateAnalytics.id)
        )
    ).scalars().all()

    return DayDetail(
        summary=summary,
        meals=[MealEntryRead.model_validate(m) for m in meals],
        workouts=[WorkoutSessionRead.model_validate(w) for w in workouts],
        heart_rate=[HeartRateAnalyticsRead.model_validate(r) for r in readings],
    )
