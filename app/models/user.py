import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.activity import DailyVitals, WorkoutSession
    from app.models.heart_rate import HeartRateAnalytics, SleepZoneBenchmarks
    from app.models.nutrition import MealEntry, NutritionLog


class User(Base):
    """User and Biometrics table (Screens 1 & 2)."""
    __tablename__ = "users"

    # UUID Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(100), default="Jonathan Sanders")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Biometrics (Screen 2)
    age: Mapped[int] = mapped_column(Integer, default=24)
    weight_kg: Mapped[float] = mapped_column(Float, default=72.2)
    height_cm: Mapped[float] = mapped_column(Float, default=176.0)
    primary_goal: Mapped[str] = mapped_column(
        String(50),
        default="Fat Burn",  # "Fat Burn", "Gaining Muscle", "Endurance", "Mindfulness"
    )
    # Auto-calculated: round((220 - age) * 0.70) => round((220 - 24) * 0.7) = 137
    target_hr_bpm: Mapped[int] = mapped_column(Integer, default=137)
    # "male", "female" or "other"; picks the private tracker (private log / period tracker)
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_onboarded: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    daily_vitals: Mapped[List["DailyVitals"]] = relationship(
        "DailyVitals", back_populates="user", cascade="all, delete-orphan"
    )
    workouts: Mapped[List["WorkoutSession"]] = relationship(
        "WorkoutSession", back_populates="user", cascade="all, delete-orphan"
    )
    heart_rate_analytics: Mapped[List["HeartRateAnalytics"]] = relationship(
        "HeartRateAnalytics", back_populates="user", cascade="all, delete-orphan"
    )
    sleep_benchmarks: Mapped[List["SleepZoneBenchmarks"]] = relationship(
        "SleepZoneBenchmarks", back_populates="user", cascade="all, delete-orphan"
    )
    nutrition_logs: Mapped[List["NutritionLog"]] = relationship(
        "NutritionLog", back_populates="user", cascade="all, delete-orphan"
    )
    meals: Mapped[List["MealEntry"]] = relationship(
        "MealEntry", back_populates="user", cascade="all, delete-orphan"
    )
