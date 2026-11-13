from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.activity import DailyVitals
from app.models.heart_rate import HeartRateAnalytics, SleepZoneBenchmarks
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


@router.get("/daily", response_model=DailyVitalsRead)
async def get_daily_vitals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns Screen 4 ('Daily Activities') Bento payload."""
    today = datetime.now(timezone.utc).date()
    stmt = select(DailyVitals).where(
        DailyVitals.user_id == current_user.id,
        DailyVitals.date == today,
    )
    res = await db.execute(stmt)
    vitals = res.scalar_one_or_none()

    if not vitals:
        vitals = DailyVitals(
            user_id=current_user.id,
            date=today,
            agenda_title="Walking",
            steps_count=7435,
            weight_kg=current_user.weight_kg or 72.2,
            weight_status="Stable Weight",
            latest_hr_bpm=101,
            hr_status="High HR",
            body_composition_pct=87.9,
            body_comp_badge="Gaining Muscle",
        )
        db.add(vitals)
        await db.commit()
        await db.refresh(vitals)

    return DailyVitalsRead.model_validate(vitals)


@router.patch("/steps", response_model=DailyVitalsRead)
async def patch_daily_steps(
    payload: StepsPatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Increments or updates daily steps and agenda (Screen 4)."""
    today = datetime.now(timezone.utc).date()
    stmt = select(DailyVitals).where(
        DailyVitals.user_id == current_user.id,
        DailyVitals.date == today,
    )
    res = await db.execute(stmt)
    vitals = res.scalar_one_or_none()

    if not vitals:
        vitals = DailyVitals(user_id=current_user.id, date=today)
        db.add(vitals)

    if payload.steps_increment is not None:
        vitals.steps_count += payload.steps_increment
    elif payload.steps_count is not None:
        vitals.steps_count = payload.steps_count

    if payload.agenda_title is not None:
        vitals.agenda_title = payload.agenda_title

    await db.commit()
    await db.refresh(vitals)
    return DailyVitalsRead.model_validate(vitals)


@router.put("/daily", response_model=DailyVitalsRead, include_in_schema=False)
async def update_daily_vitals(
    payload: DailyVitalsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates daily vitals (weight, steps, body composition)."""
    today = datetime.now(timezone.utc).date()
    stmt = select(DailyVitals).where(
        DailyVitals.user_id == current_user.id,
        DailyVitals.date == today,
    )
    res = await db.execute(stmt)
    vitals = res.scalar_one_or_none()

    if not vitals:
        vitals = DailyVitals(user_id=current_user.id, date=today)
        db.add(vitals)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(vitals, field, value)

    if payload.weight_kg is not None:
        current_user.weight_kg = payload.weight_kg

    await db.commit()
    await db.refresh(vitals)
    return DailyVitalsRead.model_validate(vitals)


@router.get("/heart-rate-zones", response_model=HeartRateZoneScreenData)
@router.get("/heart-rate-zone", response_model=HeartRateZoneScreenData, include_in_schema=False)
async def get_heart_rate_zones(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns Screen 5 ('Target Heart Rate Zone') 7-bar time-series + age benchmark ranges."""
    today = datetime.now(timezone.utc).date()

    # Query 7 vertical chart bars
    hr_stmt = (
        select(HeartRateAnalytics)
        .where(HeartRateAnalytics.user_id == current_user.id)
        .order_by(HeartRateAnalytics.id.asc())
        .limit(7)
    )
    hr_res = await db.execute(hr_stmt)
    bars = hr_res.scalars().all()

    # Seed 7 canonical slots if empty
    if not bars or len(bars) < 7:
        sample_bars = [
            ("06:00", 102, "Fat Burn", False),
            ("08:00", 134, "Fat Burn", True),  # Active Peak Bar
            ("10:00", 115, "Fat Burn", False),
            ("12:00", 98, "Below zones", False),
            ("14:00", 122, "Fat Burn", False),
            ("16:00", 140, "Fat Burn", False),
            ("18:00", 108, "Below zones", False),
        ]
        created_bars = []
        for slot, bpm, zone, is_peak in sample_bars:
            log_item = HeartRateAnalytics(
                user_id=current_user.id,
                recorded_date=today,
                slot_label=slot,
                bpm_value=bpm,
                zone_type=zone,
                is_peak=is_peak,
            )
            db.add(log_item)
            created_bars.append(log_item)
        await db.commit()
        bars = created_bars

    # Query or create sleep benchmark ranges
    bench_stmt = select(SleepZoneBenchmarks).where(
        SleepZoneBenchmarks.user_id == current_user.id,
        SleepZoneBenchmarks.recorded_date == today,
    )
    bench_res = await db.execute(bench_stmt)
    bench = bench_res.scalar_one_or_none()

    if not bench:
        bench = SleepZoneBenchmarks(
            user_id=current_user.id,
            recorded_date=today,
            light_pct="40-60%",
            rem_pct="15-25%",
            deep_pct="8-16%",
            awake_pct="12-24%",
        )
        db.add(bench)
        await db.commit()
        await db.refresh(bench)

    return HeartRateZoneScreenData(
        target_hr_bpm=current_user.target_hr_bpm or 137,
        primary_goal=current_user.primary_goal or "Fat Burn",
        latest_hr_bpm=101,
        hr_status="High HR",
        chart_bars=[HeartRateAnalyticsRead.model_validate(b) for b in bars],
        benchmarks=SleepZoneBenchmarksRead.model_validate(bench),
    )


@router.post("/heart-rate-log", response_model=HeartRateAnalyticsRead, status_code=status.HTTP_201_CREATED)
async def create_heart_rate_log(
    payload: HeartRateAnalyticsCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Logs a live heart rate telemetry point."""
    today = datetime.now(timezone.utc).date()
    log = HeartRateAnalytics(
        user_id=current_user.id,
        recorded_date=today,
        slot_label=payload.slot_label,
        bpm_value=payload.bpm_value,
        zone_type=payload.zone_type,
        is_peak=payload.is_peak,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return HeartRateAnalyticsRead.model_validate(log)
