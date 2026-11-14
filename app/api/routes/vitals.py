from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
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
from app.schemas.heart_rate import HeartRateSyncRequest, HeartRateSyncResponse
from app.schemas.heart_rate import (
    HeartRateAnalyticsCreate,
    HeartRateAnalyticsRead,
    HeartRateZoneScreenData,
    SleepZoneBenchmarksRead,
)

router = APIRouter(prefix="/vitals", tags=["Vitals & Heart Rate Analytics (Screens 4 & 5)"])

# How far back the phone may backfill steps / heart rate (e.g. app not opened
# for a few days while the step service kept counting)
BACKFILL_DAYS = 30


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
    """
    Records steps for today (or a recent day via for_date).
    steps_at_least: the phone's own total for that day; only ever raises the
    stored count, so resending it is safe and two sources never double count.
    """
    day = today
    if payload.for_date is not None:
        if not (today - timedelta(days=BACKFILL_DAYS) <= payload.for_date <= today):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Steps can only be recorded for the last {BACKFILL_DAYS} days",
            )
        day = payload.for_date
    vitals = await get_or_create_daily(db, DailyVitals, current_user, day)

    if payload.steps_at_least is not None:
        floor = payload.steps_at_least
        vitals.steps_count = case(
            (DailyVitals.steps_count < floor, floor), else_=DailyVitals.steps_count
        )
    elif payload.steps_increment is not None:
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
    vitals = await save_daily_vitals(
        db, current_user, today, **payload.model_dump(exclude_unset=True)
    )
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


@router.post("/heart-rate-sync", response_model=HeartRateSyncResponse)
async def sync_heart_rate(
    payload: HeartRateSyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """
    Imports heart-rate readings from Health Connect (watch / fitness apps).
    Readings already stored (same day, time and bpm) are skipped, so the app
    can safely resend after a failed sync.
    """
    oldest = today - timedelta(days=BACKFILL_DAYS)
    readings = [r for r in payload.readings if oldest <= r.date <= today]
    if not readings:
        return HeartRateSyncResponse(imported=0, skipped=len(payload.readings))

    existing = set(
        (await db.execute(
            select(HeartRateAnalytics.recorded_date, HeartRateAnalytics.slot_label, HeartRateAnalytics.bpm_value)
            .where(
                HeartRateAnalytics.user_id == current_user.id,
                HeartRateAnalytics.recorded_date.in_({r.date for r in readings}),
            )
        )).all()
    )

    imported = 0
    latest_today = None
    for r in sorted(readings, key=lambda r: (r.date, r.slot_label)):
        key = (r.date, r.slot_label, r.bpm_value)
        if key in existing:
            continue
        existing.add(key)
        db.add(HeartRateAnalytics(
            user_id=current_user.id,
            recorded_date=r.date,
            slot_label=r.slot_label,
            bpm_value=r.bpm_value,
            zone_type=hr_zone_label(r.bpm_value, current_user.target_hr_bpm),
            is_peak=False,
        ))
        imported += 1
        if r.date == today:
            latest_today = r.bpm_value

    if latest_today is not None:
        vitals = await get_or_create_daily(db, DailyVitals, current_user, today)
        vitals.latest_hr_bpm = latest_today
        vitals.hr_status = hr_zone_label(latest_today, current_user.target_hr_bpm)

    await db.commit()
    return HeartRateSyncResponse(imported=imported, skipped=len(payload.readings) - imported)


# ---------------------------------------------------------------------------
# Shared logic (also used by the AI assistant)
# ---------------------------------------------------------------------------

async def save_daily_vitals(db: AsyncSession, user: User, day: date, **fields) -> DailyVitals:
    """Updates a day's vitals; a weight also becomes the profile weight."""
    vitals = await get_or_create_daily(db, DailyVitals, user, day)
    for field, value in fields.items():
        setattr(vitals, field, value)
    if fields.get("weight_kg") is not None:
        user.weight_kg = fields["weight_kg"]
    await db.commit()
    await db.refresh(vitals)
    return vitals
