"""Health-check endpoint: {"status": "ok"} — a simple liveness probe."""

from fastapi import APIRouter

from backend.modules.health.update import get_update_info
from backend.version import APP_VERSION


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Simple backend liveness check + installed version (settings page)."""
    return {"status": "ok", "version": APP_VERSION}


@router.get("/update")
def update() -> dict:
    """Is a newer release available on GitHub? Fail-open: offline = no."""
    return get_update_info()
