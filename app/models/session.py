"""
Response models for session aggregation and analytics.

These models structure the enriched data returned by session
analysis endpoints — talk ratios, speaker breakdowns, and
formatted transcripts.
"""

from pydantic import BaseModel, Field


class SpeakerStats(BaseModel):
    """Aggregated statistics for a single speaker."""

    speaker: str
    segment_count: int = 0
    word_count: int = 0
    talk_ratio: float = Field(
        default=0.0,
        description="Percentage of total words spoken by this speaker (0–100).",
    )


class SessionSummary(BaseModel):
    """High-level summary of a conversation session."""

    session_id: str
    total_segments: int = 0
    total_words: int = 0
    speakers: list[SpeakerStats] = []
    duration_seconds: float | None = Field(
        default=None,
        description="Elapsed time from first to last segment timestamp.",
    )


class FormattedTranscript(BaseModel):
    """Full transcript formatted with speaker labels and timestamps."""

    session_id: str
    lines: list[dict] = Field(
        default_factory=list,
        description="Ordered transcript lines with speaker, text, and timestamp.",
    )
    plain_text: str = Field(
        default="",
        description="Plain-text transcript with speaker prefixes.",
    )
