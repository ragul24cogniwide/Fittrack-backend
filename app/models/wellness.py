"""Private trackers: masturbation log (men) and period tracker (women)."""
import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MasturbationLog(Base):
    """One logged session, at the phone's local wall-clock time."""
    __tablename__ = "masturbation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date_type] = mapped_column(Date, index=True)  # device-local day
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))  # local time
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PeriodLog(Base):
    """One period: first day, last day (empty while it is still going) and flow."""
    __tablename__ = "period_logs"
    __table_args__ = (UniqueConstraint("user_id", "start_date", name="uq_period_logs_user_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date_type] = mapped_column(Date, index=True)
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    flow: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # light / medium / heavy
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
