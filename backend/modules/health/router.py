"""Health-check endpoint: {"status": "ok"} — a simple liveness probe."""

from fastapi import APIRouter

from backend.modules.health.update import get_update_info


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Simple backend liveness check."""
    return {"status": "ok"}


@router.get("/update")
def update() -> dict:
    """Is a newer release available on GitHub? Fail-open: offline = no."""
    return get_update_info()
