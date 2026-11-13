"""Shared helpers for per-user, per-day rows (daily vitals, nutrition log)."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Type, TypeVar

from fastapi import Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import DailyVitals
from app.models.nutrition import NutritionLog
from app.models.user import User

T = TypeVar("T", DailyVitals, NutritionLog)


def client_today(
    x_tz_offset_minutes: Optional[int] = Header(
        None,
        description="JS Date.getTimezoneOffset() of the device, e.g. -330 for IST",
    ),
) -> date:
    """FastAPI dependency: the calendar date on the user's device (falls back to UTC)."""
    now = datetime.now(timezone.utc)
    if x_tz_offset_minutes is not None and -840 <= x_tz_offset_minutes <= 840:
        now = now - timedelta(minutes=x_tz_offset_minutes)
    return now.date()


async def get_or_create_daily(
    db: AsyncSession, model: Type[T], user: User, day: date
) -> T:
    """
    Returns the user's row for `day`, creating it if missing.
    A unique (user_id, date) constraint guards against concurrent creates from
    the app's live polling; on conflict we roll back and re-read the winner.
    """
    stmt = select(model).where(model.user_id == user.id, model.date == day)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row

    if model is DailyVitals:
        row = DailyVitals(user_id=user.id, date=day, weight_kg=user.weight_kg)
    else:
        row = NutritionLog(user_id=user.id, date=day)
    try:
        # SAVEPOINT: a conflict rolls back only this insert, so other objects
        # in the session (e.g. current_user) stay loaded.
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        return (await db.execute(stmt)).scalar_one()
    await db.commit()
    return row


def week_start(day: date) -> date:
    """Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def hr_zone_label(bpm: int, target_hr_bpm: int) -> str:
    """Classifies a heart-rate reading relative to the user's target zone."""
    if bpm <= 0:
        return ""
    if bpm < target_hr_bpm * 0.85:
        return "Below zones"
    if bpm <= target_hr_bpm * 1.15:
        return "Fat Burn"
    return "Peak"

