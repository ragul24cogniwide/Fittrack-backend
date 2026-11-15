"""
Sleep tracking: nights come from the phone's sleep detection (Google Sleep
API), from Health Connect (watches / sleep apps) or are entered by the user.
"""
import math
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today
from app.api.deps import get_current_user, get_db
from app.models.sleep import SleepSession
from app.models.user import User
from app.schemas.sleep import (
    SleepConfirmIn,
    SleepNight,
    SleepSessionIn,
    SleepSessionRead,
    SleepStages,
    SleepSummary,
)

router = APIRouter(prefix="/sleep", tags=["Sleep"])

GOAL_MIN = 8 * 60  # adults: 7-9 h recommended; 8 h is the middle
BACKFILL_DAYS = 30
# A better source replaces a worse one, never the other way round:
# what the user entered > a watch / sleep app > the phone's estimate
SOURCE_RANK = {"phone": 1, "health_connect": 2, "manual": 3}


def night_score(asleep_min: int, awake_min: Optional[int], rating: Optional[int]) -> int:
    """
    0-100 for one night:
    - duration: 100 for 7-9 h asleep, -20 per hour under 7, -10 per hour over 9
    - interruptions (if known): -1 per 5 min awake beyond 20 min, at most -15
    - rating (if given): 30% of the score (1 = 20 ... 5 = 100)
    """
    if asleep_min <= 0:
        return 0
    hours = asleep_min / 60
    if hours < 7:
        duration = 100 - (7 - hours) * 20
    elif hours > 9:
        duration = 100 - (hours - 9) * 10
    else:
        duration = 100.0
    if awake_min:
        duration -= min(15, max(0, awake_min - 20) / 5)
    duration = max(0.0, duration)
    score = duration if rating is None else duration * 0.7 + rating * 20 * 0.3
    return round(max(0.0, min(100.0, score)))


def _read(s: SleepSession) -> SleepSessionRead:
    out = SleepSessionRead.model_validate(s)
    out.score = night_score(s.asleep_min, s.awake_min, s.rating)
    return out


def _bedtime_minutes(start: datetime) -> int:
    """Bedtime as minutes after noon, so 23:30 and 00:30 are 60 min apart (not 23 h)."""
    m = start.hour * 60 + start.minute - 12 * 60
    return m if m >= 0 else m + 24 * 60


def _clock(minutes_after_noon: float) -> str:
    total = int(round(minutes_after_noon + 12 * 60)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


async def save_sleep(
    db: AsyncSession,
    user: User,
    today: date,
    start: datetime,
    end: datetime,
    source: str,
    stages: Optional[SleepStages] = None,
    rating: Optional[int] = None,
) -> SleepSession:
    """
    Stores a night under its wake-up day. Raises ValueError for impossible input.
    A lower-ranked source never overwrites a higher one (it is ignored), and the
    user's rating is kept when a better source replaces the times.
    """
    start = start.replace(tzinfo=None, second=0, microsecond=0)
    end = end.replace(tzinfo=None, second=0, microsecond=0)
    minutes = int((end - start).total_seconds() // 60)
    if minutes < 30 or minutes > 16 * 60:
        raise ValueError("Sleep must be between 30 minutes and 16 hours long")
    day = end.date()
    if day > today or day < today - timedelta(days=BACKFILL_DAYS):
        raise ValueError(f"Sleep can only be recorded for the last {BACKFILL_DAYS} days")

    awake = stages.awake_min if stages else None
    asleep = minutes - (awake or 0)
    if stages and (stages.light_min + stages.deep_min + stages.rem_min) > 0:
        asleep = min(asleep, stages.light_min + stages.deep_min + stages.rem_min) or asleep

    stmt = select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date == day)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing and SOURCE_RANK[source] < SOURCE_RANK.get(existing.source, 0):
        return existing  # e.g. phone estimate arriving after the user corrected it

    row = existing or SleepSession(user_id=user.id, date=day)
    row.start_local, row.end_local = start, end
    row.asleep_min = max(0, asleep)
    row.awake_min = awake
    row.light_min = stages.light_min if stages else None
    row.deep_min = stages.deep_min if stages else None
    row.rem_min = stages.rem_min if stages else None
    row.source = source
    if rating is not None:
        row.rating = rating
    row.confirmed = source == "manual" or (existing.confirmed if existing else False)
    if existing is None:
        try:
            async with db.begin_nested():
                db.add(row)
        except IntegrityError:
            # Another sync created the night at the same moment: retry as an update
            return await save_sleep(db, user, today, start, end, source, stages, rating)
    await db.commit()
    await db.refresh(row)
    return row


@router.put("/sessions", response_model=SleepSessionRead)
async def put_sleep_session(
    payload: SleepSessionIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Saves a night (phone detection, Health Connect or entered by the user)."""
    try:
        row = await save_sleep(
            db, current_user, today, payload.start, payload.end,
            payload.source, payload.stages, payload.rating,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _read(row)


@router.post("/sessions/{day}/confirm", response_model=SleepSessionRead)
async def confirm_sleep_session(
    day: date,
    payload: SleepConfirmIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The morning check: 'Yes, that's right' (optionally with how rested you feel)."""
    row = (
        await db.execute(
            select(SleepSession).where(SleepSession.user_id == current_user.id, SleepSession.date == day)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sleep recorded for that night")
    row.confirmed = True
    if payload.rating is not None:
        row.rating = payload.rating
    await db.commit()
    await db.refresh(row)
    return _read(row)


@router.delete("/sessions/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sleep_session(
    day: date,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Removes a wrong night (e.g. the phone thought you slept while it lay on a desk)."""
    row = (
        await db.execute(
            select(SleepSession).where(SleepSession.user_id == current_user.id, SleepSession.date == day)
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return None


def _tip(last: Optional[SleepSession], avg_min: int, debt_min: int, variation: Optional[int],
         avg_bedtime: Optional[str]) -> str:
    if last is None and avg_min == 0:
        return "Keep your phone near your bed tonight, or log your sleep in the morning."
    if last is not None and last.asleep_min < 6 * 60:
        target = _clock(_bedtime_minutes(last.start_local) - 60) if last else "23:00"
        return f"Short night. Try to be in bed by {target} tonight to catch up."
    if variation is not None and variation > 60:
        return f"Your bedtime moves a lot (±{variation} min). A steady bedtime around {avg_bedtime} helps you sleep better."
    if debt_min >= 5 * 60:
        return f"You're {debt_min // 60} h short of your sleep goal this week. An earlier night or two will help."
    if avg_min >= 7 * 60:
        return "Great sleep this week. Keep the same routine."
    return "Aim for 7-9 hours. A regular bedtime and no screens in the last hour help."


@router.get("/summary", response_model=SleepSummary)
async def sleep_summary(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Last night plus the trend: average, sleep debt, bedtime consistency, a tip."""
    start = today - timedelta(days=days - 1)
    rows: List[SleepSession] = list(
        (
            await db.execute(
                select(SleepSession)
                .where(SleepSession.user_id == current_user.id, SleepSession.date.between(start, today))
                .order_by(SleepSession.date)
            )
        ).scalars()
    )
    by_day = {r.date: r for r in rows}
    nights = []
    d = start
    while d <= today:
        r = by_day.get(d)
        nights.append(
            SleepNight(
                date=d,
                asleep_min=r.asleep_min if r else 0,
                bedtime=r.start_local.strftime("%H:%M") if r else None,
                wake_time=r.end_local.strftime("%H:%M") if r else None,
                score=night_score(r.asleep_min, r.awake_min, r.rating) if r else 0,
            )
        )
        d += timedelta(days=1)

    logged = len(rows)
    avg_min = round(sum(r.asleep_min for r in rows) / logged) if logged else 0
    avg_score = round(sum(night_score(r.asleep_min, r.awake_min, r.rating) for r in rows) / logged) if logged else 0
    debt = sum(max(0, GOAL_MIN - r.asleep_min) for r in rows)

    variation = avg_bedtime = None
    if logged:
        mins = [_bedtime_minutes(r.start_local) for r in rows]
        mean = sum(mins) / len(mins)
        avg_bedtime = _clock(mean)
        if logged >= 3:
            variation = round(math.sqrt(sum((m - mean) ** 2 for m in mins) / len(mins)))

    last = by_day.get(today)
    return SleepSummary(
        goal_min=GOAL_MIN,
        last_night=_read(last) if last else None,
        nights=nights,
        nights_logged=logged,
        avg_asleep_min=avg_min,
        avg_score=avg_score,
        sleep_debt_min=debt,
        bedtime_variation_min=variation,
        avg_bedtime=avg_bedtime,
        tip=_tip(last, avg_min, debt, variation, avg_bedtime),
    )
