import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=4)


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field("Jonathan Sanders", max_length=100)
    avatar_url: Optional[str] = None


class UserGoogleLogin(BaseModel):
    """Google OAuth Payload from mobile app."""
    id_token: Optional[str] = None
    email: EmailStr
    full_name: Optional[str] = "Google User"
    avatar_url: Optional[str] = None
    google_id: Optional[str] = None


class UserOnboardingUpdate(BaseModel):
    """Biometrics & Goals calibration (Screen 2)."""
    age: int = Field(24, ge=12, le=120)
    weight_kg: float = Field(72.2, gt=20.0, lt=400.0)
    height_cm: float = Field(176.0, gt=50.0, lt=300.0)
    primary_goal: str = Field(
        "Fat Burn",
        description="'Fat Burn', 'Gaining Muscle', 'Endurance', 'Mindfulness'",
    )
    target_hr_bpm: Optional[int] = Field(
        None,
        description="Auto-calculated if omitted: round((220 - age) * 0.70)",
    )


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    avatar_url: Optional[str] = None
    is_active: bool
    is_onboarded: bool

    # Biometrics
    age: int
    weight_kg: float
    height_cm: float
    primary_goal: str
    target_hr_bpm: int

    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
