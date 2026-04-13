"""
JWT Authentication module for eDNA LPT API.

Provides user authentication, token generation, and verification utilities.
Phase 6A: JWT Authentication implementation.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from passlib.context import CryptContext
from jwt import encode, decode, ExpiredSignatureError, InvalidTokenError
import os

# Security context for password hashing (using argon2)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# HTTP security scheme
security = HTTPBearer(auto_error=False)

# ============================================================================
# Configuration
# ============================================================================

class JWTSettings:
    """JWT configuration settings."""
    
    SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    @property
    def access_token_expiry(self) -> timedelta:
        return timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    @property
    def refresh_token_expiry(self) -> timedelta:
        return timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)


@lru_cache
def get_jwt_settings() -> JWTSettings:
    """Get JWT settings (cached)."""
    return JWTSettings()


# ============================================================================
# Data Models
# ============================================================================

class UserBase(BaseModel):
    """Base user model."""
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """User creation schema."""
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")


class UserResponse(UserBase):
    """User response schema (no password)."""
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    is_active: bool = True
    
    model_config = ConfigDict(from_attributes=True)


class TokenRequest(BaseModel):
    """Token request (login) schema."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response schema."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Seconds until token expires")


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema."""
    refresh_token: str


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # subject (user email)
    exp: datetime  # expiration time
    iat: datetime  # issued at
    type: str = "access"  # token type: access or refresh


# ============================================================================
# Password utilities
# ============================================================================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ============================================================================
# JWT Token utilities
# ============================================================================

def create_access_token(email: str, settings: JWTSettings) -> str:
    """
    Create a JWT access token.
    
    Args:
        email: User email (subject)
        settings: JWT settings
        
    Returns:
        Encoded JWT token string
    """
    now = datetime.now(timezone.utc)
    expires_at = now + settings.access_token_expiry
    
    payload = {
        "sub": email,
        "iat": now,
        "exp": expires_at,
        "type": "access"
    }
    
    token = encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token


def create_refresh_token(email: str, settings: JWTSettings) -> str:
    """
    Create a JWT refresh token.
    
    Args:
        email: User email (subject)
        settings: JWT settings
        
    Returns:
        Encoded JWT token string
    """
    now = datetime.now(timezone.utc)
    expires_at = now + settings.refresh_token_expiry
    
    payload = {
        "sub": email,
        "iat": now,
        "exp": expires_at,
        "type": "refresh"
    }
    
    token = encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), 
                settings: JWTSettings = Depends(get_jwt_settings)) -> str:
    """
    Verify a JWT access token from Authorization header.
    
    Args:
        credentials: HTTPAuthorizationCredentials from Authorization header
        settings: JWT settings
        
    Returns:
        User email (token subject) if valid
        
    Raises:
        HTTPException: If token is invalid, expired, or missing
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = credentials.credentials
    
    try:
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # Verify token type is "access"
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return email
        
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )


def verify_refresh_token(token: str, settings: JWTSettings) -> str:
    """
    Verify a JWT refresh token (used in request body, not header).
    
    Args:
        token: Refresh token string
        settings: JWT settings
        
    Returns:
        User email if valid
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # Verify token type is "refresh"
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
        
        return email
        
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired"
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {str(e)}"
        )


# ============================================================================
# Mock User Database (for development)
# ============================================================================
# TODO: Replace with SQLAlchemy models and PostgreSQL in Phase 6B

_users_db = {}  # In-memory user store: {email: {"email": str, "hashed_password": str}}


def create_user(user_create: UserCreate) -> UserResponse:
    """
    Create a new user in the mock database.
    
    Args:
        user_create: User creation data
        
    Returns:
        Created user response
        
    Raises:
        ValueError: If user already exists
    """
    if user_create.email in _users_db:
        raise ValueError(f"User {user_create.email} already exists")
    
    _users_db[user_create.email] = {
        "email": user_create.email,
        "full_name": user_create.full_name or user_create.email.split("@")[0],
        "hashed_password": hash_password(user_create.password),
        "created_at": datetime.now(timezone.utc),
        "is_active": True
    }
    
    return UserResponse(
        email=user_create.email,
        full_name=_users_db[user_create.email]["full_name"],
        created_at=_users_db[user_create.email]["created_at"]
    )


def get_user(email: str) -> Optional[dict]:
    """
    Get a user from the mock database.
    
    Args:
        email: User email
        
    Returns:
        User dict or None if not found
    """
    return _users_db.get(email)


def authenticate_user(email: str, password: str) -> bool:
    """
    Authenticate a user by email and password.
    
    Args:
        email: User email
        password: Plain password
        
    Returns:
        True if credentials valid, False otherwise
    """
    user = get_user(email)
    if not user:
        return False
    return verify_password(password, user["hashed_password"])
