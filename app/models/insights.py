"""
Pydantic models for sales insights.

Each insight represents a detected pattern in the conversation —
an objection, buying signal, competitor mention, or next-step commitment.
"""

from enum import Enum

from pydantic import BaseModel, Field


class InsightType(str, Enum):
    """Categories of detectable sales insights."""

    PRICING_OBJECTION = "pricing_objection"
    BUYING_SIGNAL = "buying_signal"
    COMPETITOR_MENTION = "competitor_mention"
    NEXT_STEP = "next_step"
    STALL_TACTIC = "stall_tactic"


class Insight(BaseModel):
    """A single detected insight from the conversation."""

    type: InsightType
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0–1.0) based on keyword match strength.",
    )
    matched_text: str = Field(
        ...,
        description="The exact transcript text that triggered this insight.",
    )
    matched_phrase: str = Field(
        ...,
        description="The keyword/phrase pattern that matched.",
    )
    speaker: str | None = None
    timestamp: float | None = None
    suggestion: str = Field(
        default="",
        description="Recommended response or action for the sales agent.",
    )


class SessionInsights(BaseModel):
    """All insights detected for a conversation session."""

    session_id: str
    insights: list[Insight] = []
    total_insights: int = 0
    summary: dict[str, int] = Field(
        default_factory=dict,
        description="Count of insights by type.",
    )
