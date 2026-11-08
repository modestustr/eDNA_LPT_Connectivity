"""
Integration tests for Phase 6A JWT Authentication endpoints.

Run with: pytest test_auth_endpoints.py -v
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime

# Create a minimal test app with just auth endpoints
from fastapi import FastAPI
from src.api.auth import (
    UserCreate, TokenRequest, RefreshTokenRequest, UserResponse, TokenResponse,
    create_user, authenticate_user, create_access_token, create_refresh_token,
    get_jwt_settings, verify_token
)

# Setup test app
app = FastAPI()

@app.post("/auth/signup", response_model=UserResponse, status_code=201)
async def signup(user_create: UserCreate):
    try:
        user = create_user(user_create)
        return user
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(e))

@app.post("/auth/login", response_model=TokenResponse)
async def login(token_request: TokenRequest):
    from fastapi import HTTPException
    settings = get_jwt_settings()
    
    if not authenticate_user(token_request.email, token_request.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    access_token = create_access_token(token_request.email, settings)
    refresh_token = create_refresh_token(token_request.email, settings)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

@app.post("/auth/refresh", response_model=TokenResponse)
async def refresh(request: RefreshTokenRequest):
    from fastapi import HTTPException
    from src.api.auth import verify_refresh_token
    
    settings = get_jwt_settings()
    
    try:
        email = verify_refresh_token(request.refresh_token, settings)
        access_token = create_access_token(email, settings)
        
        return TokenResponse(
            access_token=access_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    except HTTPException:
        raise

# Test client
client = TestClient(app)


class TestAuthSignup:
    """Test signup endpoint."""
    
    def test_signup_success(self):
        """Test successful user signup."""
        response = client.post("/auth/signup", json={
            "email": "newuser@example.com",
            "password": "SecurePass123!",
            "full_name": "New User"
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["full_name"] == "New User"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
    
    def test_signup_duplicate_email(self):
        """Test signup fails for duplicate email."""
        # First signup
        client.post("/auth/signup", json={
            "email": "duplicate@example.com",
            "password": "Pass123!",
        })
        
        # Try to signup again with same email
        response = client.post("/auth/signup", json={
            "email": "duplicate@example.com",
            "password": "Different123!",
        })
        
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]


class TestAuthLogin:
    """Test login endpoint."""
    
    def test_login_success(self):
        """Test successful login."""
        # Create user first
        client.post("/auth/signup", json={
            "email": "logintest@example.com",
            "password": "LoginPass123!",
        })
        
        # Login
        response = client.post("/auth/login", json={
            "email": "logintest@example.com",
            "password": "LoginPass123!",
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 30 * 60  # 30 minutes in seconds
    
    def test_login_invalid_password(self):
        """Test login fails with wrong password."""
        # Create user
        client.post("/auth/signup", json={
            "email": "passtest@example.com",
            "password": "CorrectPass123!",
        })
        
        # Try login with wrong password
        response = client.post("/auth/login", json={
            "email": "passtest@example.com",
            "password": "WrongPass123!",
        })
        
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]
    
    def test_login_nonexistent_email(self):
        """Test login fails for non-existent user."""
        response = client.post("/auth/login", json={
            "email": "nonexistent@example.com",
            "password": "AnyPass123!",
        })
        
        assert response.status_code == 401


class TestAuthRefresh:
    """Test token refresh endpoint."""
    
    def test_refresh_token_success(self):
        """Test successful token refresh."""
        # Create user and login
        client.post("/auth/signup", json={
            "email": "refreshtest@example.com",
            "password": "RefreshPass123!",
        })
        
        login_response = client.post("/auth/login", json={
            "email": "refreshtest@example.com",
            "password": "RefreshPass123!",
        })
        
        refresh_token = login_response.json()["refresh_token"]
        
        # Refresh token
        response = client.post("/auth/refresh", json={
            "refresh_token": refresh_token
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
    
    def test_refresh_invalid_token(self):
        """Test refresh fails with invalid token."""
        response = client.post("/auth/refresh", json={
            "refresh_token": "invalid.token.signature"
        })
        
        assert response.status_code == 401


class TestTokenFormat:
    """Test JWT token format and content."""
    
    def test_token_is_jwt_format(self):
        """Test that tokens are valid JWT format."""
        # Create user and login
        client.post("/auth/signup", json={
            "email": "jwttest@example.com",
            "password": "JWTPass123!",
        })
        
        login_response = client.post("/auth/login", json={
            "email": "jwttest@example.com",
            "password": "JWTPass123!",
        })
        
        access_token = login_response.json()["access_token"]
        
        # JWT format: header.payload.signature
        parts = access_token.split(".")
        assert len(parts) == 3, "Token should have 3 parts separated by dots"
        
        # Decode payload to verify structure
        import base64
        import json
        
        # Add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding:
            payload += "=" * padding
        
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        assert "sub" in decoded  # Subject (email)
        assert "iat" in decoded  # Issued at
        assert "exp" in decoded  # Expiration
        assert "type" in decoded  # Token type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
