import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


async def _get_or_create_nutrition_log(
    user_id: uuid.UUID, db: AsyncSession, target_date: Optional[date_type] = None
) -> NutritionLog:
    """Helper to retrieve today's NutritionLog or seed default values matching Screen 6."""
    active_date = target_date or datetime.now(timezone.utc).date()
    stmt = (
        select(NutritionLog)
        .options(selectinload(NutritionLog.meals))
        .where(
            NutritionLog.user_id == user_id,
            NutritionLog.date == active_date,
        )
    )
    res = await db.execute(stmt)
    nutr = res.scalar_one_or_none()

    if not nutr:
        nutr = NutritionLog(
            user_id=user_id,
            date=active_date,
            calories_consumed=1840,
            calories_goal=2400,
            protein_g=142,
            carbs_g=210,
            fats_g=58,
            water_liters=2.5,
            water_goal_liters=3.0,
            metabolic_score_pct=92,
        )
        db.add(nutr)
        await db.commit()
        await db.refresh(nutr)

        # Seed initial meals matching Screen 6
        initial_meals = [
            ("Breakfast", "Oatmeal & Wild Berries", 420, 18),
            ("Lunch", "Grilled Chicken Quinoa Bowl", 680, 54),
            ("Snacks", "Greek Yogurt & Roasted Almonds", 240, 22),
            ("Dinner", "Wild Atlantic Salmon & Sweet Potato", 500, 48),
        ]
        for m_type, title, cal, p in initial_meals:
            meal_item = MealEntry(
                user_id=user_id,
                nutrition_log_id=nutr.id,
                meal_type=m_type,
                title=title,
                calories=cal,
                protein_g=p,
            )
            db.add(meal_item)
        await db.commit()

        # Reload with meals
        stmt = (
            select(NutritionLog)
            .options(selectinload(NutritionLog.meals))
            .where(NutritionLog.id == nutr.id)
        )
        res = await db.execute(stmt)
        nutr = res.scalar_one()

    return nutr


@router.get("/today", response_model=NutritionLogRead)
@router.get("/daily", response_model=NutritionLogRead, include_in_schema=False)
async def get_today_nutrition(
    meal_type: Optional[str] = Query(None, description="Filter: Breakfast, Lunch, Dinner, Snacks"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns Screen 6 calories, macro progress bars, hydration liters, metabolic score, and meal list."""
    nutr = await _get_or_create_nutrition_log(current_user.id, db)

    calories_pct = round((nutr.calories_consumed / max(1, nutr.calories_goal)) * 100)
    calories_remaining = max(0, nutr.calories_goal - nutr.calories_consumed)
    water_pct = round((nutr.water_liters / max(0.1, nutr.water_goal_liters)) * 100)

    meals = nutr.meals
    if meal_type and meal_type.lower() != "all meals":
        meals = [m for m in meals if m.meal_type.lower() == meal_type.lower()]

    return NutritionLogRead(
        id=nutr.id,
        user_id=nutr.user_id,
        date=nutr.date,
        calories_consumed=nutr.calories_consumed,
        calories_goal=nutr.calories_goal,
        calories_remaining=calories_remaining,
        calories_pct=calories_pct,
        protein_g=nutr.protein_g,
        carbs_g=nutr.carbs_g,
        fats_g=nutr.fats_g,
        water_liters=nutr.water_liters,
        water_goal_liters=nutr.water_goal_liters,
        water_pct=water_pct,
        metabolic_score_pct=nutr.metabolic_score_pct,
        meals=[MealEntryRead.model_validate(m) for m in meals],
    )


@router.post("/hydration", response_model=HydrationStatusResponse)
async def increment_hydration(
    payload: Optional[WaterLogRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Increments water_liters by +0.25L and returns updated hydration status."""
    nutr = await _get_or_create_nutrition_log(current_user.id, db)

    delta = payload.delta_liters if (payload and payload.delta_liters is not None) else 0.25
    if payload and payload.set_liters is not None:
        nutr.water_liters = round(max(0.0, min(10.0, payload.set_liters)), 2)
    else:
        nutr.water_liters = round(max(0.0, min(10.0, nutr.water_liters + delta)), 2)

    await db.commit()
    await db.refresh(nutr)

    water_pct = round((nutr.water_liters / max(0.1, nutr.water_goal_liters)) * 100)
    return HydrationStatusResponse(
        water_liters=nutr.water_liters,
        water_goal_liters=nutr.water_goal_liters,
        water_pct=water_pct,
        metabolic_score_pct=nutr.metabolic_score_pct,
    )


@router.post("/water", response_model=NutritionLogRead, include_in_schema=False)
async def log_water_legacy(
    payload: WaterLogRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Screen 6 interactive 6-pill water logging."""
    await increment_hydration(payload, current_user, db)
    return await get_today_nutrition(None, current_user, db)


@router.post("/meals", response_model=MealEntryRead, status_code=status.HTTP_201_CREATED)
async def log_meal(
    payload: MealEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Logs a new meal and recalculates daily calories and macros."""
    nutr = await _get_or_create_nutrition_log(current_user.id, db)

    meal = MealEntry(
        user_id=current_user.id,
        nutrition_log_id=nutr.id,
        meal_type=payload.meal_type,
        title=payload.title,
        calories=payload.calories,
        protein_g=payload.protein_g,
    )
    db.add(meal)

    # Increment totals
    nutr.calories_consumed += payload.calories
    nutr.protein_g += payload.protein_g

    await db.commit()
    await db.refresh(meal)
    return MealEntryRead.model_validate(meal)


@router.delete("/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal(
    meal_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes a meal and deducts its calories/macros from the daily summary."""
    stmt = select(MealEntry).where(
        MealEntry.id == meal_id,
        MealEntry.user_id == current_user.id,
    )
    res = await db.execute(stmt)
    meal = res.scalar_one_or_none()

    if not meal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found")

    if meal.nutrition_log_id:
        nutr_stmt = select(NutritionLog).where(NutritionLog.id == meal.nutrition_log_id)
        nutr_res = await db.execute(nutr_stmt)
        nutr = nutr_res.scalar_one_or_none()
        if nutr:
            nutr.calories_consumed = max(0, nutr.calories_consumed - meal.calories)
            nutr.protein_g = max(0, nutr.protein_g - meal.protein_g)

    await db.delete(meal)
    await db.commit()
    return None
