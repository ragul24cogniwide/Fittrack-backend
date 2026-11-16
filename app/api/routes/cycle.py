"""
Period tracker for women: log periods, see the current cycle day and the
predicted next period / fertile window. Profiles must be set to Female.
Predictions are estimates from the user's own history (calendar method).
"""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today
from app.api.deps import get_db, require_gender
from app.models.user import User
from app.models.wellness import PeriodLog
from app.schemas.wellness import CycleSummary, PeriodIn, PeriodRead, PeriodUpdate

router = APIRouter(prefix="/cycle", tags=["Period tracker"])

DEFAULT_CYCLE_DAYS = 28
DEFAULT_PERIOD_DAYS = 5
MAX_PERIOD_DAYS = 14
# A period without an end date counts as still going for at most this long
OPEN_PERIOD_DAYS = 10
LUTEAL_DAYS = 14  # ovulation is ~14 days before the next period
HISTORY_DAYS = 2 * 365
require_female = require_gender("female")


def _read(p: PeriodLog) -> PeriodRead:
    out = PeriodRead.model_validate(p)
    out.length_days = (p.end_date - p.start_date).days + 1 if p.end_date else None
    return out


def _is_ongoing(p: PeriodLog, today: date) -> bool:
    if p.start_date > today:
        return False
    if p.end_date is not None:
        # The user tapped "ended": from then on it's over, even on its last day
        return False
    return (today - p.start_date).days < OPEN_PERIOD_DAYS


def _effective_end(p: PeriodLog, today: date) -> date:
    """Last day a period covers, for overlap checks."""
    if p.end_date is not None:
        return p.end_date
    if _is_ongoing(p, today):
        return today
    return p.start_date + timedelta(days=DEFAULT_PERIOD_DAYS - 1)


async def _periods(db: AsyncSession, user: User) -> List[PeriodLog]:
    return list(
        (
            await db.execute(
                select(PeriodLog).where(PeriodLog.user_id == user.id).order_by(PeriodLog.start_date)
            )
        ).scalars()
    )


def _validate(
    start: date, end: Optional[date], others: List[PeriodLog], today: date
) -> None:
    if start > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The start date can't be in the future")
    if start < today - timedelta(days=HISTORY_DAYS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That date is too far back")
    if end is not None:
        if end < start:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The end date is before the start date")
        if end > today:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The end date can't be in the future")
        if (end - start).days + 1 > MAX_PERIOD_DAYS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"A period can be at most {MAX_PERIOD_DAYS} days long"
            )
    new_end = end or (today if (today - start).days < OPEN_PERIOD_DAYS else start)
    for p in others:
        if start <= _effective_end(p, today) and p.start_date <= new_end:
            if p.end_date is None and _is_ongoing(p, today):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Your period from {p.start_date:%d %b} is still going. Mark it as ended first.",
                )
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"This overlaps your period from {p.start_date:%d %b}"
            )


@router.post("/periods", response_model=PeriodRead, status_code=status.HTTP_201_CREATED)
async def add_period(
    payload: PeriodIn,
    current_user: User = Depends(require_female),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Logs a period: today ('it started') or a past one with its end date."""
    _validate(payload.start_date, payload.end_date, await _periods(db, current_user), today)
    row = PeriodLog(
        user_id=current_user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        flow=payload.flow,
    )
    try:
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A period already starts on that day")
    await db.commit()
    await db.refresh(row)
    return _read(row)


@router.patch("/periods/{period_id}", response_model=PeriodRead)
async def update_period(
    period_id: int,
    payload: PeriodUpdate,
    current_user: User = Depends(require_female),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Marks a period as ended, changes its dates or flow."""
    row = await db.get(PeriodLog, period_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Period not found")
    start = payload.start_date or row.start_date
    end = payload.end_date if "end_date" in payload.model_fields_set else row.end_date
    others = [p for p in await _periods(db, current_user) if p.id != row.id]
    _validate(start, end, others, today)
    row.start_date, row.end_date = start, end
    if payload.flow is not None:
        row.flow = payload.flow
    await db.commit()
    await db.refresh(row)
    return _read(row)


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_period(
    period_id: int,
    current_user: User = Depends(require_female),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(PeriodLog, period_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Period not found")
    await db.delete(row)
    await db.commit()
    return None


def _tip(s: CycleSummary) -> str:
    if not s.periods:
        return "Log the first day of your last period to see your cycle and predictions."
    if s.on_period:
        return (
            f"Period day {s.period_day}. Drink enough water; gentle movement like walking "
            "or yoga can ease cramps."
        )
    if s.days_until_next is not None and s.days_until_next < 0:
        late = -s.days_until_next
        return (
            f"Your period is {late} day{'s' if late != 1 else ''} later than usual. Stress, "
            "sleep, travel and training load can shift your cycle."
        )
    if s.days_until_next is not None and s.days_until_next <= 3:
        if s.days_until_next == 0:
            return "Your period may start today."
        return f"Your period may start in {s.days_until_next} day{'s' if s.days_until_next != 1 else ''}."
    if s.phase == "fertile":
        return "You're in your predicted fertile window."
    if s.phase == "follicular":
        return "Energy is often higher in this phase, a good time for harder workouts."
    if s.phase == "luteal":
        return "You may feel more tired before your period. Prioritise sleep and recovery."
    return "Keep logging your periods to make the predictions more accurate."


@router.get("/summary", response_model=CycleSummary)
async def cycle_summary(
    current_user: User = Depends(require_female),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Cycle day, phase, averages and the predicted next period / fertile window."""
    periods = [p for p in await _periods(db, current_user) if p.start_date <= today]

    gaps = [
        (b.start_date - a.start_date).days for a, b in zip(periods, periods[1:])
    ]
    gaps = [g for g in gaps if 18 <= g <= 60][-6:]
    avg_cycle = round(sum(gaps) / len(gaps)) if gaps else DEFAULT_CYCLE_DAYS
    lengths = [
        (p.end_date - p.start_date).days + 1 for p in periods if p.end_date is not None
    ][-6:]
    avg_period = round(sum(lengths) / len(lengths)) if lengths else DEFAULT_PERIOD_DAYS

    summary = CycleSummary(
        periods=[_read(p) for p in reversed(periods[-12:])],
        cycles_logged=len(periods),
        avg_cycle_days=avg_cycle,
        avg_period_days=avg_period,
        on_period=False,
        tip="",
    )
    if periods:
        last = periods[-1]
        summary.on_period = _is_ongoing(last, today)
        summary.cycle_day = (today - last.start_date).days + 1
        if summary.on_period:
            summary.period_day = summary.cycle_day
        next_start = last.start_date + timedelta(days=avg_cycle)
        ovulation = next_start - timedelta(days=LUTEAL_DAYS)
        summary.next_period_start = next_start
        summary.days_until_next = (next_start - today).days
        summary.ovulation_date = ovulation
        summary.fertile_start = ovulation - timedelta(days=5)
        summary.fertile_end = ovulation + timedelta(days=1)
        if summary.on_period:
            summary.phase = "period"
        elif summary.days_until_next < 0:
            summary.phase = "late"
        elif summary.fertile_start <= today <= summary.fertile_end:
            summary.phase = "fertile"
        elif today < summary.fertile_start:
            summary.phase = "follicular"
        else:
            summary.phase = "luteal"
    summary.tip = _tip(summary)
    return summary
