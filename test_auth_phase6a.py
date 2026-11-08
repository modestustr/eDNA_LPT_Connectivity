"""
Test script for Phase 6A JWT Authentication endpoints.

Run with: python test_auth_phase6a.py
"""

import sys
import json
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Test auth module directly
from src.api.auth import (
    UserCreate, hash_password, verify_password,
    create_access_token, create_refresh_token, verify_token,
    create_user, authenticate_user, get_jwt_settings, JWTSettings
)


def test_password_hashing():
    """Test password hashing and verification."""
    print("\n=== Test 1: Password Hashing ===")
    password = "MySecurePassword123!"
    
    hashed = hash_password(password)
    print(f"✓ Original password hashed successfully")
    print(f"  Hashed: {hashed[:50]}...")
    
    # Verify correct password
    assert verify_password(password, hashed), "Should verify correct password"
    print(f"✓ Correct password verified")
    
    # Verify incorrect password
    assert not verify_password("WrongPassword", hashed), "Should reject incorrect password"
    print(f"✓ Incorrect password rejected")


def test_user_creation():
    """Test user creation and retrieval."""
    print("\n=== Test 2: User Creation ===")
    
    user_create = UserCreate(
        email="testuser@example.com",
        password="TestPassword123!",
        full_name="Test User"
    )
    
    user = create_user(user_create)
    print(f"✓ User created: {user.email}")
    print(f"  Full name: {user.full_name}")
    print(f"  Created at: {user.created_at}")
    
    # Try to create duplicate
    try:
        create_user(user_create)
        assert False, "Should reject duplicate user"
    except ValueError as e:
        print(f"✓ Duplicate user rejected: {str(e)}")


def test_authentication():
    """Test user authentication."""
    print("\n=== Test 3: User Authentication ===")
    
    # Create test user
    user_create = UserCreate(
        email="authtest@example.com",
        password="AuthPassword123!",
        full_name="Auth Test"
    )
    create_user(user_create)
    
    # Test correct credentials
    assert authenticate_user("authtest@example.com", "AuthPassword123!")
    print(f"✓ Correct credentials authenticated")
    
    # Test incorrect password
    assert not authenticate_user("authtest@example.com", "WrongPassword")
    print(f"✓ Incorrect password rejected")
    
    # Test non-existent user
    assert not authenticate_user("nonexistent@example.com", "AnyPassword")
    print(f"✓ Non-existent user rejected")


def test_token_creation():
    """Test JWT token creation."""
    print("\n=== Test 4: JWT Token Creation ===")
    
    settings = get_jwt_settings()
    email = "tokentest@example.com"
    
    access_token = create_access_token(email, settings)
    print(f"✓ Access token created")
    print(f"  Length: {len(access_token)} chars")
    print(f"  Parts: {len(access_token.split('.'))}")
    
    refresh_token = create_refresh_token(email, settings)
    print(f"✓ Refresh token created")
    print(f"  Length: {len(refresh_token)} chars")
    
    # Verify tokens are different
    assert access_token != refresh_token
    print(f"✓ Tokens are distinct")


def test_token_verification():
    """Test JWT token verification."""
    print("\n=== Test 5: JWT Token Verification ===")
    
    from jwt import decode
    
    settings = get_jwt_settings()
    email = "verifytest@example.com"
    
    # Create access token
    access_token = create_access_token(email, settings)
    
    # Decode and inspect payload
    payload = decode(access_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    print(f"✓ Access token decoded")
    print(f"  Subject (email): {payload.get('sub')}")
    print(f"  Type: {payload.get('type')}")
    print(f"  Issued: {payload.get('iat')}")
    print(f"  Expires: {payload.get('exp')}")
    
    assert payload['sub'] == email
    assert payload['type'] == 'access'
    print(f"✓ Token payload verified")
    
    # Create refresh token
    refresh_token = create_refresh_token(email, settings)
    refresh_payload = decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    
    assert refresh_payload['type'] == 'refresh'
    print(f"✓ Refresh token type verified")


def test_token_expiry():
    """Test token expiry configuration."""
    print("\n=== Test 6: Token Expiry Settings ===")
    
    settings = get_jwt_settings()
    
    print(f"✓ Access token expiry: {settings.ACCESS_TOKEN_EXPIRE_MINUTES} minutes")
    print(f"✓ Refresh token expiry: {settings.REFRESH_TOKEN_EXPIRE_DAYS} days")
    print(f"✓ Algorithm: {settings.ALGORITHM}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("JWT Authentication Tests (Phase 6A)")
    print("=" * 60)
    
    try:
        test_password_hashing()
        test_user_creation()
        test_authentication()
        test_token_creation()
        test_token_verification()
        test_token_expiry()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Update config/.env with JWT_SECRET_KEY")
        print("2. Test endpoints with: python run.py")
        print("3. Visit: http://localhost:8505")
        print("4. Try POST /auth/signup in API docs")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
