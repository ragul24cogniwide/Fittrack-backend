from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy 2.0 ORM models."""
    pass


# Import all models here so that Base.metadata.create_all registers all tables
from app.models.user import User  # noqa: E402, F401
from app.models.activity import DailyVitals, WorkoutSession  # noqa: E402, F401
from app.models.heart_rate import HeartRateAnalytics, SleepZoneBenchmarks  # noqa: E402, F401
from app.models.nutrition import NutritionLog, MealEntry  # noqa: E402, F401
from app.models.sleep import SleepSession  # noqa: E402, F401

