from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today, get_or_create_daily, hr_zone_label
from app.api.deps import get_current_user, get_db
from app.models.activity import DailyVitals
from app.models.heart_rate import HeartRateAnalytics
from app.models.user import User
from app.schemas.activity import (
    DailyVitalsRead,
    DailyVitalsUpdate,
    StepsPatchRequest,
)
from app.schemas.heart_rate import (
    HeartRateAnalyticsCreate,
    HeartRateAnalyticsRead,
    HeartRateZoneScreenData,
    SleepZoneBenchmarksRead,
)

router = APIRouter(prefix="/vitals", tags=["Vitals & Heart Rate Analytics (Screens 4 & 5)"])


async def _weight_status(db: AsyncSession, user: User, vitals: DailyVitals) -> str:
    """Compares today's weight with the most recent earlier reading."""
    prev = (
        await db.execute(
            select(DailyVitals.weight_kg)
            .where(DailyVitals.user_id == user.id, DailyVitals.date < vitals.date)
            .order_by(DailyVitals.date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prev is None:
        return "First Reading"
    delta = round(vitals.weight_kg - prev, 1)
    if abs(delta) < 0.2:
        return "Stable Weight"
    return f"{'Up' if delta > 0 else 'Down'} {abs(delta)} kg"


@router.get("/daily", response_model=DailyVitalsRead)
async def get_daily_vitals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Returns Screen 4 ('Daily Activities') payload for the device's current day."""
    vitals = await get_or_create_daily(db, DailyVitals, current_user, today)
    result = DailyVitalsRead.model_validate(vitals)
    result.weight_status = await _weight_status(db, current_user, vitals)
    return result


@router.patch("/steps", response_model=DailyVitalsRead)
async def patch_daily_steps(
    payload: StepsPatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Adds steps counted by the phone's step sensor (or sets an explicit total)."""
    vitals = await get_or_create_daily(db, DailyVitals, current_user, today)

    if payload.steps_increment is not None:
        # Atomic increment so concurrent syncs never lose steps
        vitals.steps_count = DailyVitals.steps_count + payload.steps_increment
    elif payload.steps_count is not None:
        vitals.steps_count = payload.steps_count
    if payload.agenda_title is not None:
        vitals.agenda_title = payload.agenda_title

    await db.commit()
    await db.refresh(vitals)
    return DailyVitalsRead.model_validate(vitals)


@router.put("/daily", response_model=DailyVitalsRead)
async def update_daily_vitals(
    payload: DailyVitalsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Updates today's vitals (e.g. a new weigh-in). Weight also updates the profile."""
    vitals = await get_or_create_daily(db, DailyVitals, current_user, today)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vitals, field, value)
    if payload.weight_kg is not None:
        current_user.weight_kg = payload.weight_kg

    await db.commit()
    await db.refresh(vitals)
    result = DailyVitalsRead.model_validate(vitals)
    result.weight_status = await _weight_status(db, current_user, vitals)
    return result


@router.get("/heart-rate-zones", response_model=HeartRateZoneScreenData)
@router.get("/heart-rate-zone", response_model=HeartRateZoneScreenData, include_in_schema=False)
async def get_heart_rate_zones(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Screen 5: today's last 7 heart-rate readings plus daily stats."""
    base = (HeartRateAnalytics.user_id == current_user.id, HeartRateAnalytics.recorded_date == today)

    latest_seven = (
        await db.execute(
            select(HeartRateAnalytics).where(*base).order_by(HeartRateAnalytics.id.desc()).limit(7)
        )
    ).scalars().all()
    bars = list(reversed(latest_seven))  # chronological, left to right

    count, avg_bpm, max_bpm = (
        await db.execute(
            select(
                func.count(HeartRateAnalytics.id),
                func.coalesce(func.avg(HeartRateAnalytics.bpm_value), 0),
                func.coalesce(func.max(HeartRateAnalytics.bpm_value), 0),
            ).where(*base)
        )
    ).one()

    target = current_user.target_hr_bpm
    peak_bpm = max((b.bpm_value for b in bars), default=0)
    chart = []
    for b in bars:
        item = HeartRateAnalyticsRead.model_validate(b)
        item.is_peak = b.bpm_value == peak_bpm
        item.zone_type = hr_zone_label(b.bpm_value, target)
        chart.append(item)

    latest_bpm = bars[-1].bpm_value if bars else 0
    return HeartRateZoneScreenData(
        target_hr_bpm=target,
        primary_goal=current_user.primary_goal,
        latest_hr_bpm=latest_bpm,
        hr_status=hr_zone_label(latest_bpm, target),
        readings_today=int(count),
        avg_bpm_today=round(float(avg_bpm)),
        max_bpm_today=int(max_bpm),
        chart_bars=chart,
        # Reference sleep-stage ranges for adults (static guidance, not user data)
        benchmarks=SleepZoneBenchmarksRead(id=0, recorded_date=today),
    )


@router.post("/heart-rate-log", response_model=HeartRateAnalyticsRead, status_code=status.HTTP_201_CREATED)
async def create_heart_rate_log(
    payload: HeartRateAnalyticsCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Logs a heart-rate reading (manual entry or from a workout) and updates today's vitals."""
    # Resolve today's row first: its create path may commit/rollback the session
    vitals = await get_or_create_daily(db, DailyVitals, current_user, today)

    zone = hr_zone_label(payload.bpm_value, current_user.target_hr_bpm)
    log = HeartRateAnalytics(
        user_id=current_user.id,
        recorded_date=today,
        slot_label=payload.slot_label,
        bpm_value=payload.bpm_value,
        zone_type=zone,
        is_peak=False,
    )
    db.add(log)
    vitals.latest_hr_bpm = payload.bpm_value
    vitals.hr_status = zone

    await db.commit()
    await db.refresh(log)
    return HeartRateAnalyticsRead.model_validate(log)
