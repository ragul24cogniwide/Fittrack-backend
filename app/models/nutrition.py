import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class NutritionLog(Base):
    """Daily nutrition summary (Calories, Protein, Carbs, Fats, Water) (Screen 6: Nutrients Details)."""
    __tablename__ = "nutrition_logs"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_nutrition_logs_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    date: Mapped[date_type] = mapped_column(
        Date,
        default=lambda: datetime.now(timezone.utc).date(),
        index=True,
    )

    # Caloric Intake (Screen 6: 1,840 / 2,400 kcal)
    calories_consumed: Mapped[int] = mapped_column(Integer, default=0)
    calories_goal: Mapped[int] = mapped_column(Integer, default=2400)

    # Macronutrients
    protein_g: Mapped[int] = mapped_column(Integer, default=0)
    carbs_g: Mapped[int] = mapped_column(Integer, default=0)
    fats_g: Mapped[int] = mapped_column(Integer, default=0)

    # Hydration (Screen 6: 2.5L / 3.0L)
    water_liters: Mapped[float] = mapped_column(Float, default=0.0)
    water_goal_liters: Mapped[float] = mapped_column(Float, default=3.0)

    # Metabolic Performance Score
    metabolic_score_pct: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="nutrition_logs")
    meals: Mapped[List["MealEntry"]] = relationship(
        "MealEntry", back_populates="nutrition_log", cascade="all, delete-orphan"
    )


class MealEntry(Base):
    """Individual meal entries logged under NutritionLog (Screen 6: Nutrients Details)."""
    __tablename__ = "meal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    nutrition_log_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("nutrition_logs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    meal_type: Mapped[str] = mapped_column(
        String(50), default="Lunch"
    )  # "Breakfast", "Lunch", "Dinner", "Snacks"
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    calories: Mapped[int] = mapped_column(Integer, default=0)
    protein_g: Mapped[int] = mapped_column(Integer, default=0)
    carbs_g: Mapped[int] = mapped_column(Integer, default=0)
    fats_g: Mapped[int] = mapped_column(Integer, default=0)

    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="meals")
    nutrition_log: Mapped[Optional["NutritionLog"]] = relationship(
        "NutritionLog", back_populates="meals"
    )
