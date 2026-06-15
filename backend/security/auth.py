"""JWT authentication for AgentIQ.

HS256 tokens with a 24h expiry, issued by ``POST /auth/token``.

Two user sources:
  * Built-in dev users (``admin`` / ``reviewer``) held in an in-memory dict so
    the demo and the test suite work offline with no database.
  * Self-registered users persisted in the Supabase ``users`` table, created via
    ``POST /auth/register`` and looked up by email at login.

PRODUCTION NOTE: the in-memory dev users (with default passwords) are for
development only — remove them or gate them behind APP_ENV before production.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

from backend.config import get_settings

logger = logging.getLogger("agentiq.auth")

ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24
MIN_PASSWORD_LENGTH = 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# DEV ONLY: passwords read from env vars, hashed at startup with bcrypt.
# For production, replace with Supabase Auth or a proper user table.
_RAW_DEV_USERS = {
    "admin": os.environ.get("DEV_ADMIN_PASSWORD", "agentiq_admin"),
    "reviewer": os.environ.get("DEV_REVIEWER_PASSWORD", "agentiq_review"),
}
_ROLES = {"admin": "admin", "reviewer": "reviewer"}
DEV_USERS = {
    username: {
        "hashed_password": pwd_context.hash(pw),
        "role": _ROLES[username],
    }
    for username, pw in _RAW_DEV_USERS.items()
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


async def authenticate_user(identifier: str, password: str) -> dict[str, str] | None:
    """Return ``{"username", "role"}`` if credentials are valid, else None.

    Resolution order: built-in dev users (by username) first, so the demo and
    tests authenticate offline without touching the database; then self-registered
    users in Supabase (by email). A database outage degrades to "no such user"
    rather than raising, so login fails closed with a 401.
    """

    dev = DEV_USERS.get(identifier)
    if dev is not None:
        if pwd_context.verify(password, dev["hashed_password"]):
            return {"username": identifier, "role": dev["role"]}
        return None

    # Self-registered users are keyed by email. Imported lazily so importing this
    # module (e.g. in tests) never requires live Supabase credentials.
    from backend.db.supabase_client import get_supabase_client

    try:
        record = await get_supabase_client().get_user_by_email(identifier)
    except Exception:
        logger.warning("user lookup failed during login", exc_info=True)
        return None
    if record is None or not pwd_context.verify(password, record["hashed_password"]):
        return None
    return {"username": record["email"], "role": record.get("role", "reviewer")}


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


class RegisterRequest(BaseModel):
    """Self-service registration payload. Email is the login identifier."""

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> dict[str, str]:
    """Create a new user (role ``reviewer``) in Supabase, then they log in.

    New accounts get the ``reviewer`` role — never ``admin`` — so registration
    cannot be used to self-grant elevated access. The password is bcrypt-hashed
    before it ever reaches the database.
    """

    from backend.db.supabase_client import UserCreate, get_supabase_client

    email = body.email.lower()
    if email in DEV_USERS:  # avoid colliding with a built-in dev account
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    client = get_supabase_client()
    try:
        existing = await client.get_user_by_email(email)
    except Exception as exc:
        logger.warning("register: user lookup failed", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    hashed = pwd_context.hash(body.password)
    try:
        await client.create_user(UserCreate(email=email, hashed_password=hashed, role="reviewer"))
    except Exception as exc:
        logger.warning("register: create_user failed", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")
    return {"email": email, "role": "reviewer"}


@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict[str, str]:
    user = await authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}
