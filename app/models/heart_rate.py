import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class HeartRateAnalytics(Base):
    """Heart Rate Analytics and 7-column chart distribution (Screen 5: Target Heart Rate Zone)."""
    __tablename__ = "heart_rate_analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    recorded_date: Mapped[date_type] = mapped_column(
        Date,
        default=lambda: datetime.now(timezone.utc).date(),
        index=True,
    )
    # 7 time slots from "Morning" to "Evening" (e.g., "06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00")
    slot_label: Mapped[str] = mapped_column(String(50), default="08:00")
    bpm_value: Mapped[int] = mapped_column(Integer, default=134)  # range 44 to 186
    zone_type: Mapped[str] = mapped_column(String(50), default="Fat Burn")  # "Below zones", "Fat Burn"
    is_peak: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="heart_rate_analytics")


class SleepZoneBenchmarks(Base):
    """Sleep & Vitals Benchmark Ranges card at bottom of Screen 5."""
    __tablename__ = "sleep_zone_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    recorded_date: Mapped[date_type] = mapped_column(
        Date,
        default=lambda: datetime.now(timezone.utc).date(),
        index=True,
    )

    light_pct: Mapped[str] = mapped_column(String(30), default="40-60%")
    rem_pct: Mapped[str] = mapped_column(String(30), default="15-25%")
    deep_pct: Mapped[str] = mapped_column(String(30), default="8-16%")
    awake_pct: Mapped[str] = mapped_column(String(30), default="12-24%")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="sleep_benchmarks")
