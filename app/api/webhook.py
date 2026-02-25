"""
Omi webhook receiver and session management endpoints.

Accepts POST requests from Omi containing live transcription segments,
validates the payload, stores segments in the session store, and returns
a fast 200 OK response.

Also exposes session analytics: summaries, speaker stats, and formatted transcripts.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.models.insights import SessionInsights
from app.models.session import FormattedTranscript, SessionSummary
from app.models.webhook import OmiWebhookPayload, WebhookResponse
from app.store.session_store import session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/omi", tags=["Omi Webhook"])

# Simple in-memory idempotency cache: key -> response
_idempotency_cache: dict[str, WebhookResponse] = {}


# ── Helpers ────────────────────────────────────────────────────────────

async def _get_session_or_404(session_id: str):
    """Retrieve a session or raise 404."""
    session = await session_store.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session


# ── Webhook ────────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive Omi transcription webhook",
    description=(
        "Accepts real-time transcription segments from Omi and stores them by session. "
        "Supports optional X-Idempotency-Key header for safe retries."
    ),
)
async def receive_webhook(
    payload: OmiWebhookPayload,
    x_idempotency_key: str | None = Header(default=None),
) -> WebhookResponse:
    """
    Handle an incoming Omi webhook event.

    1. Check idempotency key (if provided) — return cached response on duplicate
    2. Validate the payload (handled automatically by Pydantic)
    3. Store segments in the session store (with deduplication)
    4. Trigger background insight analysis
    5. Return 200 OK immediately
    """
    # Idempotency: return cached response if key was already processed
    if x_idempotency_key and x_idempotency_key in _idempotency_cache:
        logger.info(
            "Idempotent replay | key=%s | session=%s",
            x_idempotency_key,
            payload.session_id,
        )
        return _idempotency_cache[x_idempotency_key]

    new_count = await session_store.add_segments(
        session_id=payload.session_id,
        segments=payload.segments,
    )

    logger.info(
        "Webhook received | session=%s | segments_in_payload=%d | new_stored=%d",
        payload.session_id,
        len(payload.segments),
        new_count,
    )

    response = WebhookResponse(
        status="ok",
        session_id=payload.session_id,
        segments_received=new_count,
    )

    # Cache the response for idempotency
    if x_idempotency_key:
        _idempotency_cache[x_idempotency_key] = response

    # Trigger insight analysis in the background (non-blocking)
    asyncio.create_task(_run_background_analysis(payload.session_id))

    return response


async def _run_background_analysis(session_id: str) -> None:
    """Run insight analysis without blocking the webhook response."""
    try:
        result = await session_store.run_analysis(session_id)
        if result:
            logger.info(
                "Background analysis done | session=%s | insights=%d",
                session_id,
                result.total_insights,
            )
    except Exception:
        logger.exception("Background analysis failed | session=%s", session_id)


@router.get(
    "/sessions",
    summary="List active sessions",
    description="Returns all active session IDs and aggregate stats.",
)
async def list_sessions() -> dict[str, Any]:
    """Return active session list and stats."""
    sessions = await session_store.list_sessions()
    stats = await session_store.get_stats()
    return {
        "sessions": sessions,
        **stats,
    }


# ── Session detail ────────────────────────────────────────────────────

@router.get(
    "/sessions/{session_id}",
    summary="Get session transcript",
    description="Returns all stored transcript segments for a given session.",
)
async def get_session(session_id: str) -> dict[str, Any]:
    """Retrieve raw transcript data for a specific session."""
    session = await _get_session_or_404(session_id)
    return session.to_dict()


@router.get(
    "/sessions/{session_id}/summary",
    response_model=SessionSummary,
    summary="Get session summary",
    description="Returns talk ratio, speaker stats, word counts, and duration.",
)
async def get_session_summary(session_id: str) -> SessionSummary:
    """Retrieve aggregated analytics for a session."""
    session = await _get_session_or_404(session_id)
    return session.get_summary()


@router.get(
    "/sessions/{session_id}/transcript",
    response_model=FormattedTranscript,
    summary="Get formatted transcript",
    description="Returns the full transcript with speaker labels, ordered by timestamp.",
)
async def get_session_transcript(session_id: str) -> FormattedTranscript:
    """Retrieve the formatted, speaker-labeled transcript."""
    session = await _get_session_or_404(session_id)
    return session.get_formatted_transcript()


# ── Insights ──────────────────────────────────────────────────────────

@router.get(
    "/sessions/{session_id}/insights",
    response_model=SessionInsights,
    summary="Get sales insights",
    description="Returns detected sales insights (objections, signals, competitors, next-steps).",
)
async def get_session_insights(session_id: str) -> SessionInsights:
    """Retrieve sales insights for a session. Runs analysis if not yet cached."""
    await _get_session_or_404(session_id)  # ensure session exists

    # Return cached insights or run fresh analysis
    insights = await session_store.get_insights(session_id)
    if insights is None:
        insights = await session_store.run_analysis(session_id)
    return insights

