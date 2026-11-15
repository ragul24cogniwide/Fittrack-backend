import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SleepSession(Base):
    """
    One night's sleep, stored under the device-local day the user woke up.
    Times are the phone's local wall-clock times (what the user sees), so
    bedtimes compare naturally across nights and time zones.
    """
    __tablename__ = "sleep_sessions"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_sleep_sessions_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date_type] = mapped_column(Date, index=True)  # wake-up day
    start_local: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    end_local: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    # Minutes actually asleep (time in bed minus awake time when stages are known)
    asleep_min: Mapped[int] = mapped_column(Integer, default=0)
    awake_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    light_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deep_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rem_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # "phone" (Google sleep detection), "health_connect" (watch / sleep app), "manual"
    source: Mapped[str] = mapped_column(String(20), default="manual")
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5, how rested
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
