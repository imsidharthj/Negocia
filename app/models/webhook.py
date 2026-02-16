"""
Pydantic models for Omi webhook payloads.

Designed for resilience:
- ``speaker`` is optional (Omi may not always provide diarization)
- ``is_user`` defaults to False when missing
- Extra fields are ignored (forward-compatible with Omi payload changes)
"""

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A single transcript segment from Omi."""

    text: str = Field(..., description="Transcribed text content")
    speaker: str | None = Field(
        default=None,
        description="Speaker label, e.g. SPEAKER_01. May be absent.",
    )
    is_user: bool = Field(
        default=False,
        description="Whether this segment is from the device user (sales agent).",
    )
    timestamp: float = Field(
        ...,
        description="Unix timestamp of the segment.",
    )

    model_config = {"extra": "ignore"}


class OmiWebhookPayload(BaseModel):
    """
    Top-level payload received from Omi via webhook POST.

    Example::

        {
            "session_id": "abc-123",
            "segments": [
                {
                    "text": "This is too expensive",
                    "speaker": "SPEAKER_02",
                    "is_user": false,
                    "timestamp": 1710000000
                }
            ]
        }
    """

    session_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the conversation session.",
    )
    segments: list[TranscriptSegment] = Field(
        ...,
        min_length=1,
        description="One or more transcript segments.",
    )

    model_config = {"extra": "ignore"}


class WebhookResponse(BaseModel):
    """Standard response returned to Omi after receiving a webhook."""

    status: str = "ok"
    session_id: str
    segments_received: int
