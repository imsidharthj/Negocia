"""
Dedicated insights API router.

Provides endpoints for retrieving, filtering, and streaming sales insights.
Separated from the webhook router for cleaner concern boundaries.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.models.insights import InsightType, SessionInsights
from app.store.session_store import session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["Insights"])


# ── Helpers ────────────────────────────────────────────────────────────

async def _get_session_or_404(session_id: str):
    """Ensure session exists or raise 404."""
    session = await session_store.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session


# ── REST Endpoints ─────────────────────────────────────────────────────

@router.get(
    "/{session_id}",
    response_model=SessionInsights,
    summary="Get all insights for a session",
    description="Returns all detected insights, optionally filtered by type and confidence.",
)
async def get_insights(
    session_id: str,
    type: InsightType | None = Query(
        default=None,
        description="Filter by insight type (e.g. pricing_objection, buying_signal).",
    ),
    min_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold (0.0–1.0).",
    ),
) -> SessionInsights:
    """
    Retrieve insights with optional filtering.

    - ``type``: return only insights of this category
    - ``min_confidence``: exclude insights below this confidence score
    """
    await _get_session_or_404(session_id)

    # Get or generate insights
    insights = await session_store.get_insights(session_id)
    if insights is None:
        insights = await session_store.run_analysis(session_id)

    # Apply filters
    filtered = insights.insights
    if type is not None:
        filtered = [i for i in filtered if i.type == type]
    if min_confidence > 0.0:
        filtered = [i for i in filtered if i.confidence >= min_confidence]

    # Rebuild summary for filtered set
    from collections import Counter
    type_counts = Counter(i.type.value for i in filtered)

    return SessionInsights(
        session_id=session_id,
        insights=filtered,
        total_insights=len(filtered),
        summary=dict(type_counts),
    )


@router.get(
    "/{session_id}/coaching",
    summary="Get coaching suggestions",
    description="Returns only the actionable coaching suggestions for the sales agent.",
)
async def get_coaching(session_id: str) -> dict[str, Any]:
    """
    Return a concise list of coaching suggestions, grouped by insight type.
    Designed for quick consumption by the sales agent during a live call.
    """
    await _get_session_or_404(session_id)

    insights = await session_store.get_insights(session_id)
    if insights is None:
        insights = await session_store.run_analysis(session_id)

    # Group suggestions by type, keep only high-confidence ones
    coaching: dict[str, list[dict[str, Any]]] = {}
    for i in insights.insights:
        if i.confidence < 0.6:
            continue
        category = i.type.value
        if category not in coaching:
            coaching[category] = []
        coaching[category].append({
            "suggestion": i.suggestion,
            "trigger": i.matched_phrase,
            "confidence": i.confidence,
        })

    return {
        "session_id": session_id,
        "coaching": coaching,
        "total_suggestions": sum(len(v) for v in coaching.values()),
    }


# ── WebSocket (Real-Time Push) ────────────────────────────────────────

@router.websocket("/{session_id}/ws")
async def insights_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time insight streaming.

    On connect, sends the latest cached insights. Then polls for
    new insights every 2 seconds and pushes updates if the count changes.

    The client can send ``{"action": "refresh"}`` to force a re-analysis.
    """
    await websocket.accept()
    logger.info("WebSocket connected | session=%s", session_id)

    last_count = 0

    try:
        while True:
            # Check for client messages (non-blocking)
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=2.0
                )
                msg = json.loads(data)
                if msg.get("action") == "refresh":
                    await session_store.run_analysis(session_id)
                    logger.info("WebSocket refresh requested | session=%s", session_id)
            except asyncio.TimeoutError:
                pass  # No client message — continue polling

            # Get current insights
            insights = await session_store.get_insights(session_id)
            if insights is None:
                insights = await session_store.run_analysis(session_id)

            if insights and insights.total_insights != last_count:
                last_count = insights.total_insights
                await websocket.send_json(insights.model_dump())

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected | session=%s", session_id)
    except Exception:
        logger.exception("WebSocket error | session=%s", session_id)
        await websocket.close(code=1011)
