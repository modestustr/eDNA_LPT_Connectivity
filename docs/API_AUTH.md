# API Authentication Guide

## Phase 6A: JWT Authentication Implementation

This document describes how to use the JWT-based authentication system in the eDNA LPT Simulation API.

## Overview

The API uses **JWT (JSON Web Tokens)** for stateless authentication:
- **Access tokens** expire after 30 minutes (configurable)
- **Refresh tokens** expire after 7 days (configurable)
- Protected endpoints require `Authorization: Bearer <access_token>` header

## Authentication Endpoints

### 1. Sign Up (Create New User)

**POST** `/auth/signup`

Create a new user account.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!",
  "full_name": "John Doe"
}
```

**Response (201 Created):**
```json
{
  "email": "user@example.com",
  "full_name": "John Doe",
  "id": 1,
  "created_at": "2024-04-13T10:30:00Z",
  "is_active": true
}
```

**Error (409 Conflict):**
```json
{
  "detail": "User user@example.com already exists"
}
```

### 2. Login

**POST** `/auth/login`

Authenticate and get access/refresh tokens.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Error (401 Unauthorized):**
```json
{
  "detail": "Invalid email or password"
}
```

### 3. Refresh Token

**POST** `/auth/refresh`

Get a new access token using a refresh token.

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Error (401 Unauthorized):**
```json
{
  "detail": "Token has expired"
}
```

## Using Protected Endpoints

All simulation execution endpoints now require authentication:

- `POST /run/single` - Execute single simulation
- `POST /run/batch` - Execute batch simulations

### Request with Token

Include the access token in the `Authorization` header:

```bash
curl -X POST http://localhost:8000/run/single \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_path": "data/sample.nc",
    "output_path": "output/run1",
    "config": {
      "particle_count": 10,
      "time_steps": 100
    }
  }'
```

### Public Endpoints (No Auth Required)

These endpoints remain public:

- `GET /health` - Health check
- `GET /health/detailed` - Detailed health status
- `GET /metrics` - Prometheus metrics
- `GET /version` - API version
- `POST /auth/signup` - User registration
- `POST /auth/login` - User login

## Client Implementation Example

### Python with `requests`

```python
import requests

BASE_URL = "http://localhost:8000"

# 1. Sign up
signup_response = requests.post(
    f"{BASE_URL}/auth/signup",
    json={
        "email": "user@example.com",
        "password": "SecurePassword123!",
        "full_name": "John Doe"
    }
)
print("Signup:", signup_response.json())

# 2. Login
login_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "user@example.com",
        "password": "SecurePassword123!"
    }
)
tokens = login_response.json()
access_token = tokens["access_token"]
print("Access Token:", access_token)

# 3. Use protected endpoint
headers = {"Authorization": f"Bearer {access_token}"}
run_response = requests.post(
    f"{BASE_URL}/run/single",
    headers=headers,
    json={
        "dataset_path": "data/sample.nc",
        "output_path": "output/run1",
        "config": {"particle_count": 10}
    }
)
print("Run Result:", run_response.json())

# 4. Refresh token when expired
refresh_response = requests.post(
    f"{BASE_URL}/auth/refresh",
    json={"refresh_token": tokens["refresh_token"]}
)
new_access_token = refresh_response.json()["access_token"]
print("New Access Token:", new_access_token)
```

### JavaScript/Node.js with `fetch`

```javascript
const BASE_URL = "http://localhost:8000";

// 1. Sign up
const signupRes = await fetch(`${BASE_URL}/auth/signup`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    email: "user@example.com",
    password: "SecurePassword123!",
    full_name: "John Doe"
  })
});
console.log("Signup:", await signupRes.json());

// 2. Login
const loginRes = await fetch(`${BASE_URL}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    email: "user@example.com",
    password: "SecurePassword123!"
  })
});
const tokens = await loginRes.json();
const accessToken = tokens.access_token;
console.log("Access Token:", accessToken);

// 3. Use protected endpoint
const runRes = await fetch(`${BASE_URL}/run/single`, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${accessToken}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    dataset_path: "data/sample.nc",
    output_path: "output/run1",
    config: { particle_count: 10 }
  })
});
console.log("Run Result:", await runRes.json());

// 4. Refresh token
const refreshRes = await fetch(`${BASE_URL}/auth/refresh`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    refresh_token: tokens.refresh_token
  })
});
const newAccessToken = (await refreshRes.json()).access_token;
console.log("New Access Token:", newAccessToken);
```

## Best Practices

1. **Store Tokens Securely**
   - Access tokens: Store in memory or short-lived session cookies
   - Refresh tokens: Store in httpOnly secure cookies (production)

2. **Handle Token Expiration**
   - Check `Authorization` response headers for 401 status
   - Automatically refresh using refresh token before expiry
   - Redirect to login if refresh fails

3. **Use HTTPS in Production**
   - Never send tokens over unencrypted HTTP
   - Set `httpOnly` and `Secure` flags on cookies

4. **Rate Limiting (Phase 6B)**
   - Implement rate limiting on `/auth/login` to prevent brute force
   - Consider exponential backoff for repeated failed attempts

## Configuration

### Environment Variables

Set in `.env` file (copy from `.env.example`):

```
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
```

### In Code

Edit `src/api/auth.py` `JWTSettings` class:

```python
class JWTSettings:
    SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    REFRESH_TOKEN_EXPIRE_DAYS = 7
```

## Phase 6B: Upcoming Improvements

- [ ] User database with SQLAlchemy + PostgreSQL
- [ ] Email verification for new accounts
- [ ] Password reset flow
- [ ] Rate limiting on sensitive endpoints
- [ ] API key support for programmatic access
- [ ] Role-based access control (RBAC)

## Troubleshooting

### 401 Unauthorized

**Problem:** "Invalid token" error when calling protected endpoint

**Solutions:**
1. Verify token format: `Authorization: Bearer <token>`
2. Check token hasn't expired (see `expires_in` from login)
3. Refresh token: POST to `/auth/refresh`
4. Re-login if refresh fails

### 422 Unprocessable Entity

**Problem:** "Invalid password" or email validation error

**Solutions:**
1. Check email format is valid
2. Verify password is at least 8 characters
3. Handle validation errors from response

### CORS Errors

**Problem:** "Access to XMLHttpRequest denied" in browser

**Solution:** API already has CORS enabled for all origins. Check:
1. API is running on correct port
2. Frontend is making requests to correct API URL
3. Browser console for specific CORS error details

## Debugging

Enable debug logging by checking startup logs:

```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     POST /auth/signup
INFO:     POST /auth/login
INFO:     Application startup complete
```

## Related Endpoints

- `GET /health` - Check API is running
- `GET /version` - Check API version
- `POST /auth/signup` - Create new account
- `POST /auth/login` - Get tokens
- `POST /auth/refresh` - Refresh access token
- `POST /run/single` - Execute simulation (protected)
