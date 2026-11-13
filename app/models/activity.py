import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class DailyVitals(Base):
    """Daily Vitals & Activities (Screen 4: Daily Activities)."""
    __tablename__ = "daily_vitals"

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

    agenda_title: Mapped[str] = mapped_column(String(100), default="Walking")
    steps_count: Mapped[int] = mapped_column(Integer, default=7435)
    weight_kg: Mapped[float] = mapped_column(Float, default=72.2)
    weight_status: Mapped[str] = mapped_column(String(50), default="Stable Weight")

    latest_hr_bpm: Mapped[int] = mapped_column(Integer, default=101)
    hr_status: Mapped[str] = mapped_column(String(50), default="High HR")

    body_composition_pct: Mapped[float] = mapped_column(Float, default=87.9)
    body_comp_badge: Mapped[str] = mapped_column(String(50), default="Gaining Muscle")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="daily_vitals")


class WorkoutSession(Base):
    """Workout sessions (Screens 3 & 7: Dashboard and Live Workout Session)."""
    __tablename__ = "workout_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    title: Mapped[str] = mapped_column(String(100), default="Running")  # "Running", "Skateboard"
    category: Mapped[str] = mapped_column(
        String(50), default="Sports"
    )  # "All", "Meditation", "Sports", "Mindfulness"
    progress_pct: Mapped[int] = mapped_column(Integer, default=80)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=2280)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=2850)
    distance_km: Mapped[float] = mapped_column(Float, default=5.2)
    pace_str: Mapped[str] = mapped_column(String(50), default="5'12\" /km")
    avg_hr_bpm: Mapped[int] = mapped_column(Integer, default=142)
    calories_burned: Mapped[int] = mapped_column(Integer, default=385)
    status: Mapped[str] = mapped_column(
        String(20), default="completed"
    )  # "in_progress", "paused", "completed"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="workouts")
