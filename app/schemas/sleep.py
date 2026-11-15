from datetime import date as date_type
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SleepStages(BaseModel):
    """Minutes in each stage (only watches / sleep apps can measure these)."""
    awake_min: int = Field(0, ge=0, le=1440)
    light_min: int = Field(0, ge=0, le=1440)
    deep_min: int = Field(0, ge=0, le=1440)
    rem_min: int = Field(0, ge=0, le=1440)


class SleepSessionIn(BaseModel):
    """A night of sleep in the phone's local wall-clock time (no time zone)."""
    start: datetime = Field(..., description="Local time the user fell asleep, e.g. 2026-11-14T23:40")
    end: datetime = Field(..., description="Local time the user woke up, e.g. 2026-11-15T06:55")
    source: Literal["phone", "health_connect", "manual"] = "manual"
    stages: Optional[SleepStages] = None
    rating: Optional[int] = Field(None, ge=1, le=5, description="How rested, 1-5")


class SleepConfirmIn(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)


class SleepSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date_type
    start_local: datetime
    end_local: datetime
    asleep_min: int
    awake_min: Optional[int] = None
    light_min: Optional[int] = None
    deep_min: Optional[int] = None
    rem_min: Optional[int] = None
    source: str
    rating: Optional[int] = None
    confirmed: bool
    score: int = 0


class SleepNight(BaseModel):
    date: date_type
    asleep_min: int = 0
    bedtime: Optional[str] = None  # "23:40"
    wake_time: Optional[str] = None  # "06:55"
    score: int = 0


class SleepSummary(BaseModel):
    goal_min: int
    last_night: Optional[SleepSessionRead] = None
    nights: List[SleepNight]  # oldest first, every day in the range
    nights_logged: int
    avg_asleep_min: int
    avg_score: int
    # Hours short of the goal over the range, nights with data only
    sleep_debt_min: int
    # How much the bedtime moves from night to night (std. deviation, minutes)
    bedtime_variation_min: Optional[int] = None
    avg_bedtime: Optional[str] = None
    tip: str
