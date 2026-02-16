"""
Health check endpoint.

Provides a lightweight probe for load balancers, uptime monitors,
and deployment readiness checks.
"""

import time
from typing import Any

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["Health"])

# Record server start time for uptime calculation
_start_time = time.time()


@router.get(
    "/health",
    summary="Health Check",
    description="Returns the current health status of the service.",
    response_model=dict[str, Any],
)
async def health_check(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Return service health, version, environment, and uptime."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - _start_time, 2),
    }
