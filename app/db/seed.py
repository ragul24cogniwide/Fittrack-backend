import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.activity import DailyVitals, WorkoutSession
from app.models.heart_rate import HeartRateAnalytics, SleepZoneBenchmarks
from app.models.nutrition import MealEntry, NutritionLog
from app.models.user import User


async def seed_demo_data(session: AsyncSession) -> dict:
    """
    Seeds or resets the exact numbers from the UI design into NeonDB:
    - User: Jonathan Sanders (24y, 72.2kg, 176cm, 137 target HR)
    - DailyVitals: 7,435 steps, 72.2 kg, 101 bpm, 87.9% body composition
    - Workouts: Running (80%), Skateboard (50%)
    - Heart Rate: 7-slot distribution (Peak: 134 bpm) + Sleep benchmarks
    - Nutrition: 1,840/2,400 kcal, 142g protein, 2.5L water, 4 meals
    """
    today = datetime.now(timezone.utc).date()

    # 1. Create or update demo user
    stmt = select(User).where(User.email == "ragul@fittrack.io")
    res = await session.execute(stmt)
    demo_user = res.scalar_one_or_none()

    if not demo_user:
        demo_user = User(
            id=uuid.uuid4(),
            email="ragul@fittrack.io",
            hashed_password=get_password_hash("password123"),
            full_name="Jonathan Sanders",
            avatar_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100",
            is_active=True,
            is_onboarded=True,
            age=24,
            weight_kg=72.2,
            height_cm=176.0,
            primary_goal="Fat Burn",
            target_hr_bpm=137,  # round((220 - 24) * 0.70) = 137
        )
        session.add(demo_user)
        await session.commit()
        await session.refresh(demo_user)
    else:
        # Reset biometrics to design values
        demo_user.full_name = "Jonathan Sanders"
        demo_user.age = 24
        demo_user.weight_kg = 72.2
        demo_user.height_cm = 176.0
        demo_user.primary_goal = "Fat Burn"
        demo_user.target_hr_bpm = 137
        demo_user.is_onboarded = True
        await session.commit()
        await session.refresh(demo_user)

    user_id = demo_user.id

    # 2. DailyVitals (Screen 4: 7,435 steps, 72.2 kg, 101 bpm, 87.9% body composition)
    await session.execute(delete(DailyVitals).where(DailyVitals.user_id == user_id, DailyVitals.date == today))
    daily_vitals = DailyVitals(
        user_id=user_id,
        date=today,
        agenda_title="Walking",
        steps_count=7435,
        weight_kg=72.2,
        weight_status="Stable Weight",
        latest_hr_bpm=101,
        hr_status="High HR",
        body_composition_pct=87.9,
        body_comp_badge="Gaining Muscle",
    )
    session.add(daily_vitals)

    # 3. Workouts (Screens 3 & 7: Running 80%, Skateboard 50%)
    await session.execute(delete(WorkoutSession).where(WorkoutSession.user_id == user_id))
    w1 = WorkoutSession(
        user_id=user_id,
        title="Running",
        category="Sports",
        status="completed",
        progress_pct=80,
        duration_seconds=2280,  # 38 min
        target_duration_seconds=2850,
        distance_km=5.2,
        pace_str="5'12\" /km",
        calories_burned=385,
        avg_hr_bpm=142,
    )
    w2 = WorkoutSession(
        user_id=user_id,
        title="Skateboard",
        category="Sports",
        status="completed",
        progress_pct=50,
        duration_seconds=1440,  # 24 min
        target_duration_seconds=2880,
        distance_km=2.1,
        pace_str="6'40\" /km",
        calories_burned=210,
        avg_hr_bpm=128,
    )
    session.add_all([w1, w2])

    # 4. Heart Rate Analytics & Sleep Benchmarks (Screen 5: Peak 134 bpm, Benchmarks)
    await session.execute(delete(HeartRateAnalytics).where(HeartRateAnalytics.user_id == user_id))
    await session.execute(delete(SleepZoneBenchmarks).where(SleepZoneBenchmarks.user_id == user_id))

    sample_bars = [
        ("06:00", 102, "Fat Burn", False),
        ("08:00", 134, "Fat Burn", True),  # Active Peak Bar
        ("10:00", 115, "Fat Burn", False),
        ("12:00", 98, "Below zones", False),
        ("14:00", 122, "Fat Burn", False),
        ("16:00", 140, "Fat Burn", False),
        ("18:00", 108, "Below zones", False),
    ]
    for slot_label, bpm_val, z_type, is_p in sample_bars:
        hr_log = HeartRateAnalytics(
            user_id=user_id,
            recorded_date=today,
            slot_label=slot_label,
            bpm_value=bpm_val,
            zone_type=z_type,
            is_peak=is_p,
        )
        session.add(hr_log)

    bench = SleepZoneBenchmarks(
        user_id=user_id,
        recorded_date=today,
        light_pct="40-60%",
        rem_pct="15-25%",
        deep_pct="8-16%",
        awake_pct="12-24%",
    )
    session.add(bench)

    # 5. NutritionLog & MealEntry (Screen 6: 1,840 / 2,400 kcal, 2.5L water)
    await session.execute(delete(MealEntry).where(MealEntry.user_id == user_id))
    await session.execute(delete(NutritionLog).where(NutritionLog.user_id == user_id, NutritionLog.date == today))

    nutrition_log = NutritionLog(
        user_id=user_id,
        date=today,
        calories_consumed=1840,
        calories_goal=2400,
        protein_g=142,
        carbs_g=210,
        fats_g=58,
        water_liters=2.5,
        water_goal_liters=3.0,
        metabolic_score_pct=92,
    )
    session.add(nutrition_log)
    await session.commit()
    await session.refresh(nutrition_log)

    meals = [
        MealEntry(
            user_id=user_id,
            nutrition_log_id=nutrition_log.id,
            meal_type="Breakfast",
            title="Oatmeal & Wild Berries",
            calories=420,
            protein_g=18,
        ),
        MealEntry(
            user_id=user_id,
            nutrition_log_id=nutrition_log.id,
            meal_type="Lunch",
            title="Grilled Chicken Quinoa Bowl",
            calories=680,
            protein_g=54,
        ),
        MealEntry(
            user_id=user_id,
            nutrition_log_id=nutrition_log.id,
            meal_type="Snacks",
            title="Greek Yogurt & Roasted Almonds",
            calories=240,
            protein_g=22,
        ),
        MealEntry(
            user_id=user_id,
            nutrition_log_id=nutrition_log.id,
            meal_type="Dinner",
            title="Wild Atlantic Salmon & Sweet Potato",
            calories=500,
            protein_g=48,
        ),
    ]
    session.add_all(meals)
    await session.commit()

    token = create_access_token(subject=str(demo_user.id))

    return {
        "status": "success",
        "message": "Demo data populated into NeonDB successfully",
        "user": {
            "id": str(demo_user.id),
            "full_name": demo_user.full_name,
            "email": demo_user.email,
            "age": demo_user.age,
            "weight_kg": demo_user.weight_kg,
            "height_cm": demo_user.height_cm,
            "primary_goal": demo_user.primary_goal,
            "target_hr_bpm": demo_user.target_hr_bpm,
        },
        "telemetry_sample": {
            "steps_count": 7435,
            "weight_kg": 72.2,
            "latest_hr_bpm": 101,
            "body_composition_pct": 87.9,
            "running_progress_pct": 80,
            "skateboard_progress_pct": 50,
            "calories_consumed": 1840,
            "calories_goal": 2400,
            "water_liters": 2.5,
            "metabolic_score_pct": 92,
        },
        "access_token": token,
        "token_type": "bearer",
    }


async def main():
    """Standalone CLI entry point: python -m app.db.seed"""
    print("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Seeding demo data into database...")
    async with AsyncSessionLocal() as session:
        result = await seed_demo_data(session)
        print("Done!")
        print("User:", result["user"]["full_name"], f"({result['user']['email']})")
        print("Demo Access Token:", result["access_token"][:30] + "...")


if __name__ == "__main__":
    asyncio.run(main())

