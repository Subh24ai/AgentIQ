"""JWT authentication for AgentIQ.

HS256 tokens with a 24h expiry, issued by ``POST /auth/token``. The user store
is an in-memory dict for development only.

PRODUCTION NOTE: This in-memory store (plaintext dev passwords) MUST be replaced
with Supabase Auth before production. Do not ship this credential map.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from backend.config import get_settings

ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24

# DEV-ONLY in-memory user store. username -> {password, role}.
# Replace with Supabase Auth before production.
_USERS: dict[str, dict[str, str]] = {
    "admin": {"password": "agentiq_admin", "role": "admin"},
    "reviewer": {"password": "agentiq_review", "role": "reviewer"},
}

# tokenUrl is relative to the app root; the auth router is mounted at /auth.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

router = APIRouter(prefix="/auth", tags=["auth"])


def create_access_token(data: dict[str, Any]) -> str:
    """Create a signed HS256 JWT with a 24h expiry."""

    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    """Return the user record if credentials are valid, else None."""

    user = _USERS.get(username)
    if user is None or user["password"] != password:
        return None
    return user


def verify_token(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    """FastAPI dependency: decode and validate a bearer token, return its claims."""

    settings = get_settings()
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise credentials_exc
    if "sub" not in payload:
        raise credentials_exc
    return payload


def require_role(*roles: str) -> Callable[..., dict[str, Any]]:
    """Build a dependency that requires the caller to hold one of ``roles``."""

    def _checker(claims: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
        if claims.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return claims

    return _checker


@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict[str, str]:
    user = authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": form_data.username, "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}
