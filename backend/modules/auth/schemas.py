"""Pydantic schemas of the auth module."""

from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    """Only the username is returned — the token stays in the DB."""

    username: str


class RegisterRequest(BaseModel):
    """Self-registration. The email is the login. On success the client is
    logged in right away (same LoginResponse). linkedin is the only
    optional field."""

    email: str
    password: str
    full_name: str
    company: str
    position: str
    linkedin: str | None = None


class ProfileResponse(BaseModel):
    """User profile (comes from the license server). username is read-only."""

    username: str
    email: str | None = None
    full_name: str | None = None
    company: str | None = None
    position: str | None = None
    linkedin: str | None = None


class ProfileUpdate(BaseModel):
    """Editable profile fields."""

    email: str | None = None
    full_name: str | None = None
    company: str | None = None
    position: str | None = None
    linkedin: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class StatusResponse(BaseModel):
    """Current authorization state.

    logged_in=False — no auth_session row.
    logged_in=True  — a row exists; status is the last verify result.
    effective_status — what the UI acts on: 'ok' allows work, 'blocked'
                       locks it (see compute_effective_status).
    """

    logged_in: bool
    username: str | None = None
    status: str | None = None  # 'ok' | 'revoked' | 'offline' | 'update_required'
    effective_status: str | None = None  # 'ok' | 'blocked'
    last_verified_at: datetime | None = None
    # Set when status='update_required'; the frontend shows it as the
    # download link in the "Install the new version" overlay.
    download_url: str | None = None
