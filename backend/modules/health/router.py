"""Health-check endpoint: {"status": "ok"} — a simple liveness probe."""

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Simple backend liveness check."""
    return {"status": "ok"}
