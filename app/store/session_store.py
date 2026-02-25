"""
In-memory session store for conversation transcripts.

Holds transcript segments grouped by ``session_id``.
Uses an ``asyncio.Lock`` to ensure safe concurrent writes
from multiple webhook requests hitting the same session.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.models.insights import SessionInsights
from app.models.session import FormattedTranscript, SessionSummary, SpeakerStats
from app.models.webhook import TranscriptSegment

# Label used when Omi doesn't provide a speaker tag
_UNKNOWN_SPEAKER = "UNKNOWN"


@dataclass
class SessionData:
    """Container for all data associated with a single conversation session."""

    session_id: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    segment_count: int = 0
    latest_insights: SessionInsights | None = None

    # ── Segment ingestion ──────────────────────────────────────────────

    def add_segments(self, new_segments: list[TranscriptSegment]) -> int:
        """
        Append new transcript segments and return the count added.

        Deduplication (by timestamp + text) prevents double-processing
        if Omi resends the same segments.
        """
        existing_keys = {
            (s.timestamp, s.text) for s in self.segments
        }
        unique = [
            s for s in new_segments
            if (s.timestamp, s.text) not in existing_keys
        ]
        self.segments.extend(unique)
        self.segment_count += len(unique)
        return len(unique)

    # ── Ordered segments ───────────────────────────────────────────────

    @property
    def ordered_segments(self) -> list[TranscriptSegment]:
        """Segments sorted chronologically by timestamp."""
        return sorted(self.segments, key=lambda s: s.timestamp)

    # ── Transcript helpers ─────────────────────────────────────────────

    @property
    def full_transcript(self) -> str:
        """Return the full transcript as a single string, ordered by timestamp."""
        return " ".join(s.text for s in self.ordered_segments)

    @property
    def duration(self) -> float | None:
        """Elapsed seconds from first to last segment, or None if < 2 segments."""
        if len(self.segments) < 2:
            return None
        ordered = self.ordered_segments
        return ordered[-1].timestamp - ordered[0].timestamp

    # ── Speaker analytics ──────────────────────────────────────────────

    def _speaker_label(self, segment: TranscriptSegment) -> str:
        """Normalize speaker labels — map None / empty to UNKNOWN."""
        return segment.speaker.strip() if segment.speaker else _UNKNOWN_SPEAKER

    def get_speaker_stats(self) -> list[SpeakerStats]:
        """
        Compute per-speaker statistics: segment count, word count, talk ratio.

        Talk ratio is the percentage of total words spoken by each speaker.
        """
        speaker_segments: dict[str, int] = defaultdict(int)
        speaker_words: dict[str, int] = defaultdict(int)

        for seg in self.segments:
            label = self._speaker_label(seg)
            speaker_segments[label] += 1
            speaker_words[label] += len(seg.text.split())

        total_words = sum(speaker_words.values()) or 1  # avoid division by zero

        return [
            SpeakerStats(
                speaker=speaker,
                segment_count=speaker_segments[speaker],
                word_count=words,
                talk_ratio=round((words / total_words) * 100, 1),
            )
            for speaker, words in speaker_words.items()
        ]

    # ── Formatted transcript ───────────────────────────────────────────

    def get_formatted_transcript(self) -> FormattedTranscript:
        """
        Build a formatted transcript with speaker-labeled lines.

        Returns both structured ``lines`` (for frontends) and a
        ``plain_text`` rendering (for analysis / LLMs).
        """
        lines = []
        plain_parts = []

        for seg in self.ordered_segments:
            label = self._speaker_label(seg)
            line = {
                "speaker": label,
                "text": seg.text,
                "timestamp": seg.timestamp,
                "is_user": seg.is_user,
            }
            lines.append(line)
            plain_parts.append(f"[{label}]: {seg.text}")

        return FormattedTranscript(
            session_id=self.session_id,
            lines=lines,
            plain_text="\n".join(plain_parts),
        )

    # ── Summary ────────────────────────────────────────────────────────

    def get_summary(self) -> SessionSummary:
        """Return a high-level session summary with speaker stats."""
        total_words = sum(len(s.text.split()) for s in self.segments)
        return SessionSummary(
            session_id=self.session_id,
            total_segments=self.segment_count,
            total_words=total_words,
            speakers=self.get_speaker_stats(),
            duration_seconds=self.duration,
        )

    # ── Serialization ──────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize session data for API responses."""
        return {
            "session_id": self.session_id,
            "segment_count": self.segment_count,
            "segments": [s.model_dump() for s in self.segments],
        }


class SessionStore:
    """
    Thread-safe in-memory store for conversation sessions.

    Each session is keyed by its ``session_id``. An asyncio lock
    protects concurrent access.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}
        self._lock = asyncio.Lock()

    async def add_segments(
        self, session_id: str, segments: list[TranscriptSegment]
    ) -> int:
        """
        Add segments to a session (creating it if needed).

        Returns the number of *new* (non-duplicate) segments added.
        """
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionData(session_id=session_id)
            return self._sessions[session_id].add_segments(segments)

    async def get_session(self, session_id: str) -> SessionData | None:
        """Retrieve session data, or None if the session doesn't exist."""
        async with self._lock:
            return self._sessions.get(session_id)

    async def run_analysis(self, session_id: str) -> SessionInsights | None:
        """
        Run the insight engine on a session's segments and cache the result.

        Import is deferred to avoid circular imports.
        """
        from app.engine.insight_engine import insight_engine

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            result = insight_engine.analyze_segments(
                segments=session.ordered_segments,
                session_id=session_id,
            )
            session.latest_insights = result
            return result

    async def get_insights(self, session_id: str) -> SessionInsights | None:
        """Return cached insights for a session, or None."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return session.latest_insights

    async def list_sessions(self) -> list[str]:
        """Return all active session IDs."""
        async with self._lock:
            return list(self._sessions.keys())

    async def get_stats(self) -> dict[str, Any]:
        """Return summary statistics across all sessions."""
        async with self._lock:
            return {
                "active_sessions": len(self._sessions),
                "total_segments": sum(
                    s.segment_count for s in self._sessions.values()
                ),
            }


# ── Module-level singleton ────────────────────────────────────────────
# Imported by the webhook router and any other module that needs access.
session_store = SessionStore()
