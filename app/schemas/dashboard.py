from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class ActivityCardSummary(BaseModel):
    id: int
    title: str  # "Running", "Skateboard"
    category: str  # "Sports", "Meditation", "Mindfulness"
    progress_pct: int  # 80, 50
    distance_km: float  # 5.2, 2.1
    duration_minutes: int  # 38, 24
    calories_burned: int  # 385, 210
    action_label: str = "Continue"


class NutrientsSummaryBar(BaseModel):
    calories_consumed: int = 1840
    calories_goal: int = 2400
    percentage: int = 76
    protein_g: int = 142
    carbs_g: int = 210
    fats_g: int = 58


class WorkoutProgressWidget(BaseModel):
    progress_pct: int = 80
    level_label: str = "Level 2 Completed"
    total_calories_burned: int = 5248
    daily_delta_calories: int = 340


class SocialProofWidget(BaseModel):
    member_count_label: str = "1,200+"
    subtext: str = "athletes training"
    avatar_urls: List[str] = [
        "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100",
        "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=100",
        "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=100",
    ]


class DashboardResponse(BaseModel):
    """Unified payload for Screen 3 ('Today, Movements+' / 'FitTrack+')."""
    model_config = ConfigDict(from_attributes=True)

    user_greeting: str = "Good Morning"
    user_name: str = "Jonathan Sanders"
    avatar_url: Optional[str] = None
    date_str: str = "Today, Nov 13"
    community_joined_count: int = 215
    workout_progress_hours: str = "10/20H"
    workout_progress_pct: int = 80
    level_label: str = "Level 2 Completed"
    total_calories_burned: int = 5248

    # Activity Categories Filter Pills
    categories: List[str] = ["All", "Meditation", "Sports", "Mindfulness"]

    # Active Activity Cards
    activity_cards: List[ActivityCardSummary]

    # Nutrients Banner
    nutrients_summary: NutrientsSummaryBar
