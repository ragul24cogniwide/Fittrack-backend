from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.activity import WorkoutSessionRead
from app.schemas.heart_rate import HeartRateAnalyticsRead
from app.schemas.nutrition import MealEntryRead
from app.schemas.sleep import SleepSessionRead


class DayHistory(BaseModel):
    """One calendar day (device-local) of tracked data. Zero = nothing recorded."""
    date: date
    steps_count: int = 0
    distance_km: float = 0.0
    weight_kg: Optional[float] = None
    calories_consumed: int = 0
    protein_g: int = 0
    water_liters: float = 0.0
    workouts: int = 0
    workout_minutes: int = 0
    workout_calories: int = 0
    hr_readings: int = 0
    avg_hr_bpm: int = 0
    sleep_minutes: int = 0  # asleep the night before (woke up on this day)


class HistoryTotals(BaseModel):
    steps: int
    avg_steps_per_day: int
    best_steps_day: Optional[date] = None
    best_steps: int
    days_step_goal_met: int
    distance_km: float
    workouts: int
    workout_minutes: int
    workout_calories: int
    avg_calories_consumed: int  # averaged over days that have meals logged
    avg_sleep_minutes: int = 0  # averaged over nights that were recorded
    nights_logged: int = 0


class HistorySummary(BaseModel):
    start_date: date
    end_date: date
    step_goal: int
    days: List[DayHistory]  # oldest first, one entry per day in the range
    totals: HistoryTotals


class DayDetail(BaseModel):
    summary: DayHistory
    sleep: Optional[SleepSessionRead] = None
    meals: List[MealEntryRead]
    workouts: List[WorkoutSessionRead]
    heart_rate: List[HeartRateAnalyticsRead]
