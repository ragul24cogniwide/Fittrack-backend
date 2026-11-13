import uuid
from datetime import date as date_type
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MealEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nutrition_log_id: Optional[int] = None
    meal_type: str  # "Breakfast", "Lunch", "Dinner", "Snacks"
    title: str
    calories: int
    protein_g: int
    carbs_g: int = 0
    fats_g: int = 0
    logged_at: datetime


class MealEntryCreate(BaseModel):
    meal_type: str = Field(..., description="'Breakfast', 'Lunch', 'Dinner', 'Snacks'")
    title: str = Field(..., min_length=2, max_length=150)
    calories: int = Field(..., ge=0, le=10000)
    protein_g: int = Field(0, ge=0, le=1000)
    carbs_g: int = Field(0, ge=0, le=2000)
    fats_g: int = Field(0, ge=0, le=1000)


class WaterLogRequest(BaseModel):
    delta_liters: Optional[float] = Field(0.25, ge=-3.0, le=3.0, description="Increment in liters e.g., +0.25L")
    set_liters: Optional[float] = Field(None, ge=0.0, le=10.0, description="Direct override e.g., 2.5")


class HydrationStatusResponse(BaseModel):
    water_liters: float
    water_goal_liters: float
    water_pct: int
    metabolic_score_pct: int


class NutritionLogRead(BaseModel):
    """Screen 6 full Nutrients Details response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    date: date_type

    # Caloric Intake & Progress
    calories_consumed: int
    calories_goal: int
    calories_remaining: int
    calories_pct: int

    # Macros
    protein_g: int
    carbs_g: int
    fats_g: int

    # Hydration
    water_liters: float
    water_goal_liters: float
    water_pct: int

    # Metabolic Score
    metabolic_score_pct: int

    # Meals
    meals: List[MealEntryRead] = []
