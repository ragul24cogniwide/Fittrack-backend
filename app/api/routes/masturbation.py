"""
Private log for men: when they masturbated. Only visible to the user;
profiles must be set to Male.
"""
from collections import Counter
from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_now
from app.api.deps import get_db, require_gender
from app.models.user import User
from app.models.wellness import MasturbationLog
from app.schemas.wellness import (
    DayCount,
    MasturbationLogIn,
    MasturbationLogRead,
    MasturbationSummary,
)

router = APIRouter(prefix="/masturbation", tags=["Private log"])

BACKFILL_DAYS = 30
LOOKBACK_DAYS = 90
DOUBLE_TAP = timedelta(minutes=2)
require_male = require_gender("male")


@router.post("/logs", response_model=MasturbationLogRead, status_code=status.HTTP_201_CREATED)
async def add_log(
    payload: MasturbationLogIn,
    current_user: User = Depends(require_male),
    db: AsyncSession = Depends(get_db),
    now: datetime = Depends(client_now),
):
    """Logs a session now, or at an earlier local time (last 30 days)."""
    at = (payload.at or now).replace(tzinfo=None, second=0, microsecond=0)
    if at > now + timedelta(minutes=5):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The time can't be in the future")
    if at.date() < now.date() - timedelta(days=BACKFILL_DAYS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"You can log up to {BACKFILL_DAYS} days back")

    if payload.at is None:
        # A double tap on "Log now" shouldn't count twice
        recent = (
            await db.execute(
                select(MasturbationLog)
                .where(
                    MasturbationLog.user_id == current_user.id,
                    MasturbationLog.logged_at >= at - DOUBLE_TAP,
                    MasturbationLog.logged_at <= at,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent is not None:
            return MasturbationLogRead.model_validate(recent)

    row = MasturbationLog(user_id=current_user.id, date=at.date(), logged_at=at)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return MasturbationLogRead.model_validate(row)


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_log(
    log_id: int,
    current_user: User = Depends(require_male),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(MasturbationLog, log_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    await db.delete(row)
    await db.commit()
    return None


@router.get("/summary", response_model=MasturbationSummary)
async def summary(
    days: int = Query(14, ge=7, le=60),
    current_user: User = Depends(require_male),
    db: AsyncSession = Depends(get_db),
    now: datetime = Depends(client_now),
):
    """Counts for today / 7 days / 30 days, weekly average, gaps and a per-day chart."""
    today = now.date()
    since = today - timedelta(days=LOOKBACK_DAYS - 1)
    rows: List[MasturbationLog] = list(
        (
            await db.execute(
                select(MasturbationLog)
                .where(MasturbationLog.user_id == current_user.id, MasturbationLog.date >= since)
                .order_by(MasturbationLog.logged_at.desc())
            )
        ).scalars()
    )
    per_day = Counter(r.date for r in rows)

    def count_since(n_days: int) -> int:
        start = today - timedelta(days=n_days - 1)
        return sum(c for d, c in per_day.items() if start <= d <= today)

    last = rows[0] if rows else (
        await db.execute(
            select(MasturbationLog)
            .where(MasturbationLog.user_id == current_user.id)
            .order_by(MasturbationLog.logged_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    longest = None
    if per_day:
        log_days: List[date] = sorted(d for d in per_day if d <= today)
        gaps = [(b - a).days - 1 for a, b in zip(log_days, log_days[1:])]
        gaps.append((today - log_days[-1]).days)  # the current run
        longest = max(gaps)

    return MasturbationSummary(
        today_count=per_day.get(today, 0),
        week_count=count_since(7),
        month_count=count_since(30),
        avg_per_week=round(count_since(28) / 4, 1),
        last_at=last.logged_at if last else None,
        days_since_last=(today - last.date).days if last else None,
        longest_gap_days=longest,
        daily=[
            DayCount(date=today - timedelta(days=i), count=per_day.get(today - timedelta(days=i), 0))
            for i in range(days - 1, -1, -1)
        ],
        recent=[MasturbationLogRead.model_validate(r) for r in rows[:5]],
    )
