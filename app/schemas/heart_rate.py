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
    slot_label: str = Field(..., description="7 time slots from Morning to Evening")
    bpm_value: int = Field(..., ge=44, le=186)
    zone_type: str = Field("Fat Burn", description="'Below zones' or 'Fat Burn'")
    is_peak: bool = False


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
    latest_hr_bpm: int = 101
    hr_status: str = "High HR"
    chart_bars: List[HeartRateAnalyticsRead]
    benchmarks: SleepZoneBenchmarksRead
