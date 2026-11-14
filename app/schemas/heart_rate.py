import uuid
from datetime import date as date_type
from datetime import datetime
from typing import List
from pydantic import BaseModel, ConfigDict, Field


class HeartRateAnalyticsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    recorded_date: date_type
    slot_label: str
    bpm_value: int
    zone_type: str
    is_peak: bool
    created_at: datetime


class HeartRateAnalyticsCreate(BaseModel):
    slot_label: str = Field(..., max_length=50, description="Device-local time label, e.g. '14:05'")
    bpm_value: int = Field(..., ge=30, le=230)
    # Ignored: the zone is computed server-side from the user's target heart rate
    zone_type: str = Field("", description="Computed by the server")
    is_peak: bool = False


class HeartRateReadingIn(BaseModel):
    date: date_type
    slot_label: str = Field(..., max_length=50, description="Device-local time, e.g. '14:30'")
    bpm_value: int = Field(..., ge=30, le=230)


class HeartRateSyncRequest(BaseModel):
    readings: List[HeartRateReadingIn] = Field(..., max_length=500)


class HeartRateSyncResponse(BaseModel):
    imported: int
    skipped: int


class SleepZoneBenchmarksRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recorded_date: date_type
    light_pct: str = "40-60%"
    rem_pct: str = "15-25%"
    deep_pct: str = "8-16%"
    awake_pct: str = "12-24%"


class HeartRateZoneScreenData(BaseModel):
    """Aggregated payload matching Screen 5 ('Target Heart Rate Zone')."""
    target_hr_bpm: int = 137
    primary_goal: str = "Fat Burn"
    latest_hr_bpm: int = 0
    hr_status: str = ""
    readings_today: int = 0
    avg_bpm_today: int = 0
    max_bpm_today: int = 0
    chart_bars: List[HeartRateAnalyticsRead]
    benchmarks: SleepZoneBenchmarksRead
