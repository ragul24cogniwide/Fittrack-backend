from datetime import date as date_type
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Flow = Literal["light", "medium", "heavy"]


# ------------------------------------------------------------------ private log
class MasturbationLogIn(BaseModel):
    at: Optional[datetime] = Field(
        None, description="Local time, e.g. 2026-11-15T22:10. Omit for 'now'."
    )


class MasturbationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    logged_at: datetime


class DayCount(BaseModel):
    date: date_type
    count: int


class MasturbationSummary(BaseModel):
    today_count: int
    week_count: int  # last 7 days, today included
    month_count: int  # last 30 days
    avg_per_week: float  # over the last 4 weeks
    last_at: Optional[datetime] = None
    days_since_last: Optional[int] = None
    longest_gap_days: Optional[int] = None  # longest run of days without, last 90 days
    daily: List[DayCount]
    recent: List[MasturbationLogRead]


# --------------------------------------------------------------- period tracker
class PeriodIn(BaseModel):
    start_date: date_type
    end_date: Optional[date_type] = None
    flow: Optional[Flow] = None


class PeriodUpdate(BaseModel):
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    flow: Optional[Flow] = None


class PeriodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    start_date: date_type
    end_date: Optional[date_type] = None
    flow: Optional[str] = None
    length_days: Optional[int] = None


Phase = Literal["period", "follicular", "fertile", "luteal", "late"]


class CycleSummary(BaseModel):
    periods: List[PeriodRead]  # newest first
    cycles_logged: int
    avg_cycle_days: int
    avg_period_days: int
    on_period: bool
    period_day: Optional[int] = None
    cycle_day: Optional[int] = None
    phase: Optional[Phase] = None
    next_period_start: Optional[date_type] = None
    days_until_next: Optional[int] = None  # negative when late
    ovulation_date: Optional[date_type] = None
    fertile_start: Optional[date_type] = None
    fertile_end: Optional[date_type] = None
    tip: str
