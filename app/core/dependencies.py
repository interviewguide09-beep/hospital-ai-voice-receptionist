from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.logging import logger
from app.database.session import get_db
from app.database.models.call_log import User

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 schema for retrieving tokens from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

import bcrypt

# We no longer use passlib because of its compatibility issues with newer bcrypt versions
def hash_password(password: str) -> str:
    """Hashes a plain text password using bcrypt."""
    if len(password) > 72:
        password = password[:72]
    # bcrypt requires bytes, so encode it
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    # decode to string for db storage
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against its bcrypt hash."""
    if len(plain_password) > 72:
        plain_password = plain_password[:72]
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a secure JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": int(expire.timestamp())})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency to retrieve and validate the authenticated dashboard user via JWT."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError as e:
        logger.error(f"JWT Decode error: {str(e)}")
        raise credentials_exception

    # 1. Allow hardcoded CP Tiwari and Owner credentials to bypass database lookup
    if username in ["admin_cp", "doctor_cp", "receptionist_cp"]:
        return User(
            id=username,
            username=username,
            email=f"{username}@cptiwari.com",
            hospital_id="hosp_default",
            is_active=True
        )
    elif username == "shiva9532":
        return User(
            id="shiva9532",
            username="shiva9532",
            email="shiva9532@gmail.com",
            hospital_id="super_admin",
            is_active=True
        )

    stmt = select(User).where(User.username == username, User.is_active == True)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user
