import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class DailyVitalsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    date: date_type
    agenda_title: str
    steps_count: int
    weight_kg: float
    weight_status: str
    latest_hr_bpm: int
    hr_status: str
    body_composition_pct: float
    body_comp_badge: str
    created_at: datetime
    updated_at: datetime


class DailyVitalsUpdate(BaseModel):
    agenda_title: Optional[str] = None
    steps_count: Optional[int] = None
    weight_kg: Optional[float] = None
    weight_status: Optional[str] = None
    latest_hr_bpm: Optional[int] = None
    hr_status: Optional[str] = None
    body_composition_pct: Optional[float] = None
    body_comp_badge: Optional[str] = None


class StepsPatchRequest(BaseModel):
    """Payload for PATCH /api/v1/vitals/steps."""
    steps_increment: Optional[int] = Field(None, ge=0, le=50000, description="Steps to add, e.g. +500")
    steps_count: Optional[int] = Field(None, ge=0, le=200000, description="Explicit new steps count")
    steps_at_least: Optional[int] = Field(
        None, ge=0, le=200000,
        description="The device's total for the day; raises the stored count to at least this",
    )
    agenda_title: Optional[str] = Field(None, description="e.g., 'Walking', 'Evening Stroll'")
    for_date: Optional[date_type] = Field(
        None,
        description="Device-local day the steps belong to (up to 30 days back). "
        "Lets the phone backfill days counted while the app was closed.",
    )


class WorkoutSessionCreate(BaseModel):
    title: str = Field("Running", description="e.g., 'Running' or 'Skateboard'")
    category: str = Field("Sports", description="'All', 'Meditation', 'Sports', 'Mindfulness'")
    target_duration_seconds: int = Field(1800, ge=60, le=6 * 3600, description="Target duration in seconds")
    distance_km: float = Field(0.0, description="Starting distance")


class WorkoutTickRequest(BaseModel):
    """Payload for PATCH /api/v1/workouts/{id}/tick."""
    duration_seconds: Optional[int] = Field(None, description="Live elapsed duration")
    distance_km: Optional[float] = Field(None, description="Live distance covered")
    live_bpm: Optional[int] = Field(None, description="Current live heart rate")
    progress_pct: Optional[int] = Field(None, description="Calculated percentage 0-100")
    calories_burned: Optional[int] = Field(None, description="Estimated calories burned")
    pace_str: Optional[str] = Field(None, max_length=50, description="Current pace string e.g., 5'12\" /km")
    steps_count: Optional[int] = Field(None, ge=0, description="Steps taken during this session")
    status: Optional[Literal["in_progress", "paused"]] = Field(None, description="Pause or resume")


class WorkoutSessionUpdate(BaseModel):
    status: Optional[str] = Field(None, description="in_progress, paused, completed")
    progress_pct: Optional[int] = None
    duration_seconds: Optional[int] = None
    distance_km: Optional[float] = None
    pace_str: Optional[str] = None
    avg_hr_bpm: Optional[int] = None
    calories_burned: Optional[int] = None


class WorkoutSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    title: str
    category: str
    progress_pct: int
    duration_seconds: int
    target_duration_seconds: int
    distance_km: float
    pace_str: str
    avg_hr_bpm: int
    calories_burned: int
    steps_count: int = 0
    status: str
    created_at: datetime
    updated_at: datetime
