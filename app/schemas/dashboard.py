from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class ActivityCardSummary(BaseModel):
    id: Optional[int] = None  # None = no session yet for this activity
    title: str  # "Running", "Skateboard"
    category: str  # "Sports", "Meditation", "Mindfulness"
    status: str = "not_started"  # not_started, in_progress, paused, completed
    progress_pct: int = 0
    distance_km: float = 0.0
    duration_minutes: int = 0
    calories_burned: int = 0
    action_label: str = "Start"


class NutrientsSummaryBar(BaseModel):
    calories_consumed: int = 0
    calories_goal: int = 2400
    percentage: int = 0
    protein_g: int = 0
    carbs_g: int = 0
    fats_g: int = 0


class DashboardResponse(BaseModel):
    """Unified payload for Screen 3 ('Today, FitTrack+'). All values are computed from the DB."""
    model_config = ConfigDict(from_attributes=True)

    user_name: str
    avatar_url: Optional[str] = None
    community_joined_count: int  # total registered athletes
    # Weekly workout time (Mon-Sun) vs weekly goal
    workout_minutes_week: int
    workout_goal_minutes_week: int
    workout_progress_hours: str  # e.g. "3.5/5H"
    workout_progress_pct: int
    workouts_completed_week: int
    total_calories_burned: int  # all-time workout calories
    steps_today: int
    categories: List[str] = ["All", "Meditation", "Sports", "Mindfulness"]
    activity_cards: List[ActivityCardSummary]
    nutrients_summary: NutrientsSummaryBar
