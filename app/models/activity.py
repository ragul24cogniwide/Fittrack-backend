import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class DailyVitals(Base):
    """Daily Vitals & Activities (Screen 4: Daily Activities)."""
    __tablename__ = "daily_vitals"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_vitals_user_date"),)

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
    steps_count: Mapped[int] = mapped_column(Integer, default=0)
    weight_kg: Mapped[float] = mapped_column(Float, default=72.2)
    weight_status: Mapped[str] = mapped_column(String(50), default="")

    latest_hr_bpm: Mapped[int] = mapped_column(Integer, default=0)  # 0 = no reading yet
    hr_status: Mapped[str] = mapped_column(String(50), default="")

    body_composition_pct: Mapped[float] = mapped_column(Float, default=0.0)
    body_comp_badge: Mapped[str] = mapped_column(String(50), default="")

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
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    pace_str: Mapped[str] = mapped_column(String(50), default="--")
    avg_hr_bpm: Mapped[int] = mapped_column(Integer, default=0)
    calories_burned: Mapped[int] = mapped_column(Integer, default=0)
    steps_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress"
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
