from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today, get_or_create_daily
from app.api.deps import get_current_user, get_db
from app.models.nutrition import MealEntry, NutritionLog
from app.models.user import User
from app.schemas.nutrition import (
    HydrationStatusResponse,
    MealEntryCreate,
    MealEntryRead,
    NutritionLogRead,
    WaterLogRequest,
)

router = APIRouter(prefix="/nutrition", tags=["Nutrition & Hydration (Screen 6)"])

PROTEIN_G_PER_KG = 1.6  # common target for active adults


def _nutrition_score(nutr: NutritionLog, weight_kg: float) -> int:
    """
    0-100 daily score from what was actually logged:
    calorie adherence to goal, hydration vs goal, and protein vs 1.6 g/kg.
    """
    if nutr.calories_consumed == 0 and nutr.water_liters == 0:
        return 0
    cal_pct = nutr.calories_consumed * 100 / max(1, nutr.calories_goal)
    calorie_score = max(0.0, 100 - abs(100 - cal_pct))
    water_score = min(100.0, nutr.water_liters * 100 / max(0.1, nutr.water_goal_liters))
    protein_goal = max(1.0, weight_kg * PROTEIN_G_PER_KG)
    protein_score = min(100.0, nutr.protein_g * 100 / protein_goal)
    return round((calorie_score + water_score + protein_score) / 3)


def _hydration(nutr: NutritionLog) -> HydrationStatusResponse:
    return HydrationStatusResponse(
        water_liters=nutr.water_liters,
        water_goal_liters=nutr.water_goal_liters,
        water_pct=round(nutr.water_liters * 100 / max(0.1, nutr.water_goal_liters)),
        metabolic_score_pct=nutr.metabolic_score_pct,
    )


@router.get("/today", response_model=NutritionLogRead)
@router.get("/daily", response_model=NutritionLogRead, include_in_schema=False)
async def get_today_nutrition(
    meal_type: Optional[str] = Query(None, description="Filter: Breakfast, Lunch, Dinner, Snacks"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Screen 6: calories, macros, hydration, nutrition score and today's meals."""
    nutr = await get_or_create_daily(db, NutritionLog, current_user, today)

    meal_stmt = (
        select(MealEntry)
        .where(MealEntry.nutrition_log_id == nutr.id)
        .order_by(MealEntry.logged_at.desc())
    )
    if meal_type and meal_type.lower() != "all meals":
        meal_stmt = meal_stmt.where(MealEntry.meal_type == meal_type)
    meals = (await db.execute(meal_stmt)).scalars().all()

    return NutritionLogRead(
        id=nutr.id,
        user_id=nutr.user_id,
        date=nutr.date,
        calories_consumed=nutr.calories_consumed,
        calories_goal=nutr.calories_goal,
        calories_remaining=max(0, nutr.calories_goal - nutr.calories_consumed),
        calories_pct=round(nutr.calories_consumed * 100 / max(1, nutr.calories_goal)),
        protein_g=nutr.protein_g,
        carbs_g=nutr.carbs_g,
        fats_g=nutr.fats_g,
        water_liters=nutr.water_liters,
        water_goal_liters=nutr.water_goal_liters,
        water_pct=round(nutr.water_liters * 100 / max(0.1, nutr.water_goal_liters)),
        metabolic_score_pct=nutr.metabolic_score_pct,
        meals=[MealEntryRead.model_validate(m) for m in meals],
    )


@router.post("/hydration", response_model=HydrationStatusResponse)
async def increment_hydration(
    payload: Optional[WaterLogRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Adds water (default +0.25 L) or sets an explicit total for today."""
    if payload and payload.set_liters is not None:
        nutr = await set_water(db, current_user, today, payload.set_liters)
    else:
        delta = payload.delta_liters if (payload and payload.delta_liters is not None) else 0.25
        nutr = await add_water(db, current_user, today, delta)
    return _hydration(nutr)


@router.post("/meals", response_model=MealEntryRead, status_code=status.HTTP_201_CREATED)
async def log_meal(
    payload: MealEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
):
    """Logs a meal and adds it to today's calorie and macro totals."""
    meal = await add_meal(
        db, current_user, today,
        meal_type=payload.meal_type, title=payload.title, calories=payload.calories,
        protein_g=payload.protein_g, carbs_g=payload.carbs_g, fats_g=payload.fats_g,
    )
    return MealEntryRead.model_validate(meal)


@router.delete("/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal(
    meal_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes a meal and subtracts it from that day's totals."""
    if not await remove_meal(db, current_user, meal_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found")
    return None


# ---------------------------------------------------------------------------
# Shared logic (also used by the AI assistant in routes/ai.py)
# ---------------------------------------------------------------------------

MEAL_TYPES = ("Breakfast", "Lunch", "Dinner", "Snacks")


async def add_meal(
    db: AsyncSession, user: User, day: date, *, meal_type: str, title: str,
    calories: int, protein_g: int = 0, carbs_g: int = 0, fats_g: int = 0,
) -> MealEntry:
    nutr = await get_or_create_daily(db, NutritionLog, user, day)
    meal = MealEntry(
        user_id=user.id,
        nutrition_log_id=nutr.id,
        meal_type=meal_type,
        title=title.strip()[:150],
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fats_g=fats_g,
    )
    db.add(meal)
    nutr.calories_consumed += calories
    nutr.protein_g += protein_g
    nutr.carbs_g += carbs_g
    nutr.fats_g += fats_g
    nutr.metabolic_score_pct = _nutrition_score(nutr, user.weight_kg)
    await db.commit()
    await db.refresh(meal)
    return meal


async def remove_meal(db: AsyncSession, user: User, meal_id: int) -> Optional[MealEntry]:
    """Deletes the user's meal and subtracts it from its day's totals. None if not found."""
    meal = (
        await db.execute(
            select(MealEntry).where(MealEntry.id == meal_id, MealEntry.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not meal:
        return None
    if meal.nutrition_log_id:
        nutr = (
            await db.execute(select(NutritionLog).where(NutritionLog.id == meal.nutrition_log_id))
        ).scalar_one_or_none()
        if nutr:
            nutr.calories_consumed = max(0, nutr.calories_consumed - meal.calories)
            nutr.protein_g = max(0, nutr.protein_g - meal.protein_g)
            nutr.carbs_g = max(0, nutr.carbs_g - meal.carbs_g)
            nutr.fats_g = max(0, nutr.fats_g - meal.fats_g)
            nutr.metabolic_score_pct = _nutrition_score(nutr, user.weight_kg)
    await db.delete(meal)
    await db.commit()
    return meal


async def set_water(db: AsyncSession, user: User, day: date, liters: float) -> NutritionLog:
    nutr = await get_or_create_daily(db, NutritionLog, user, day)
    nutr.water_liters = round(max(0.0, min(10.0, liters)), 2)
    nutr.metabolic_score_pct = _nutrition_score(nutr, user.weight_kg)
    await db.commit()
    await db.refresh(nutr)
    return nutr


async def add_water(db: AsyncSession, user: User, day: date, delta_liters: float) -> NutritionLog:
    nutr = await get_or_create_daily(db, NutritionLog, user, day)
    return await set_water(db, user, day, nutr.water_liters + delta_liters)


async def list_meals(db: AsyncSession, nutr: NutritionLog):
    return (
        await db.execute(
            select(MealEntry)
            .where(MealEntry.nutrition_log_id == nutr.id)
            .order_by(MealEntry.logged_at.desc())
        )
    ).scalars().all()
