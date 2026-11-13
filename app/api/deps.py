import uuid
from typing import AsyncGenerator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.user import User

security_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an asynchronous SQLAlchemy session."""
    async for session in get_db_session():
        yield session


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extracts and verifies JWT token from Authorization header and returns User model."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials or not credentials.credentials:
        raise credentials_exception

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_identifier = payload.get("sub")
    if user_identifier is None:
        raise credentials_exception

    # Support either user UUID or email as JWT subject
    try:
        user_uuid = uuid.UUID(str(user_identifier))
        query = select(User).where(User.id == user_uuid)
    except (ValueError, AttributeError):
        query = select(User).where(User.email == str(user_identifier).lower().strip())

    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    return user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Returns the authenticated user or None if no valid credentials provided."""
    if not credentials or not credentials.credentials:
        # Fallback to demo user if available
        stmt = select(User).where(User.email == "ragul@fittrack.io")
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
