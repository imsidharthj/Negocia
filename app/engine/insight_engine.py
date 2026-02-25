"""
Rule-based sales insight engine.

Scans transcript segments for keywords and phrases that indicate
pricing objections, buying signals, competitor mentions, next-step
commitments, and stall tactics.

Design:
- Each rule category has a list of (phrase, confidence, suggestion) tuples.
- The engine lowercases text and checks for substring matches.
- A sliding window can be applied to analyze only recent segments.
- Results are deduplicated by (type, matched_phrase, timestamp) to avoid
  repeated insights from the same segment.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field

from app.models.insights import Insight, InsightType, SessionInsights
from app.models.webhook import TranscriptSegment

logger = logging.getLogger(__name__)


# ── Rule Definitions ───────────────────────────────────────────────────
# Each rule: (phrase_to_match, confidence, suggestion_for_agent)

@dataclass(frozen=True)
class Rule:
    """A single detection rule."""
    phrase: str
    confidence: float
    suggestion: str


# Pricing objection patterns
PRICING_OBJECTION_RULES: list[Rule] = [
    Rule("too expensive", 0.9, "Acknowledge the concern, then pivot to ROI and value delivered."),
    Rule("over our budget", 0.9, "Ask what their budget range is — explore flexible pricing or phased rollout."),
    Rule("out of budget", 0.9, "Ask what their budget range is — explore flexible pricing or phased rollout."),
    Rule("can't afford", 0.85, "Explore payment plans or a smaller starter package."),
    Rule("cost is too high", 0.85, "Break down the cost per user/month to reframe the investment."),
    Rule("pricing is steep", 0.8, "Compare against the cost of NOT solving the problem."),
    Rule("cheaper option", 0.8, "Differentiate on value, support, and total cost of ownership."),
    Rule("price is a concern", 0.8, "Validate their concern, then present a business case with projected savings."),
    Rule("budget constraints", 0.75, "Propose a phased implementation to spread costs."),
    Rule("not in the budget", 0.85, "Ask about their budget cycle — can this be planned for next quarter?"),
    Rule("spend that much", 0.7, "Anchor the conversation on business impact, not just price."),
]

# Buying signal patterns
BUYING_SIGNAL_RULES: list[Rule] = [
    Rule("send me a proposal", 0.95, "Prepare and send the proposal within 24 hours. Strike while interest is hot."),
    Rule("send a proposal", 0.95, "Prepare and send the proposal within 24 hours. Strike while interest is hot."),
    Rule("ready to move forward", 0.95, "Confirm the scope and timeline, then initiate onboarding steps."),
    Rule("move forward", 0.9, "Clarify the next step — contract review, pilot, or sign-off."),
    Rule("sign the contract", 0.95, "Prepare the contract and schedule a signing call."),
    Rule("start a pilot", 0.9, "Define the pilot scope, success criteria, and timeline."),
    Rule("when can we start", 0.9, "Provide a concrete onboarding timeline."),
    Rule("how soon can", 0.85, "This signals urgency — respond with a fast-track option."),
    Rule("ready to buy", 0.95, "Close the deal. Confirm the order details and next steps."),
    Rule("let's do it", 0.85, "Confirm their decision and outline the immediate next steps."),
    Rule("looks good", 0.6, "Positive signal — ask a closing question to advance the deal."),
    Rule("interested in", 0.5, "Moderate interest — explore what specifically excites them."),
    Rule("i like", 0.5, "Positive sentiment — reinforce the value they see."),
]

# Competitor mention patterns
COMPETITOR_MENTION_RULES: list[Rule] = [
    Rule("competitor", 0.8, "Ask what they like about the competitor, then differentiate on your strengths."),
    Rule("alternative solution", 0.75, "Understand their evaluation criteria and position your unique advantages."),
    Rule("other vendor", 0.8, "Ask where they are in the evaluation — are they actively comparing?"),
    Rule("other provider", 0.8, "Ask where they are in the evaluation — are they actively comparing?"),
    Rule("looking at other", 0.7, "Understand their timeline and what would make them choose you."),
    Rule("comparing with", 0.8, "Ask what criteria matter most — tailor your pitch accordingly."),
    Rule("evaluated another", 0.75, "Ask what they learned and how you can address any gaps."),
    Rule("switching from", 0.85, "They're already considering a change — understand their pain points with the current solution."),
]

# Next-step commitment patterns
NEXT_STEP_RULES: list[Rule] = [
    Rule("schedule a follow-up", 0.9, "Suggest specific dates/times. Don't leave it open-ended."),
    Rule("book a meeting", 0.9, "Send a calendar invite before they leave the call."),
    Rule("set up a demo", 0.9, "Confirm the demo scope and who should attend."),
    Rule("loop in my team", 0.85, "Great — ask who specifically and offer to present to them."),
    Rule("get back to you", 0.6, "Pin down a specific date: 'When works best to reconnect?'"),
    Rule("follow up next week", 0.8, "Confirm the day and send a calendar hold."),
    Rule("talk to my manager", 0.7, "Offer to join the internal discussion or provide a one-pager for their manager."),
    Rule("internal discussion", 0.65, "Ask what information they need for the internal discussion."),
    Rule("discuss internally", 0.65, "Offer a concise summary document they can share internally."),
]

# Stall tactic patterns
STALL_TACTIC_RULES: list[Rule] = [
    Rule("not a priority right now", 0.85, "Ask what IS a priority and whether this problem will get worse over time."),
    Rule("maybe next quarter", 0.7, "Understand what changes next quarter and create urgency for acting sooner."),
    Rule("need more time", 0.6, "Ask what specific information they need to make a decision."),
    Rule("think about it", 0.65, "Ask what specific concerns remain — try to address them now."),
    Rule("not ready yet", 0.7, "Ask what would make them ready and what's blocking the decision."),
    Rule("timing isn't right", 0.75, "Explore what would make the timing right — is there a triggering event?"),
    Rule("circle back later", 0.6, "Pin down a specific date and send a calendar invite."),
]

# Map insight types to their rule sets
_RULE_MAP: dict[InsightType, list[Rule]] = {
    InsightType.PRICING_OBJECTION: PRICING_OBJECTION_RULES,
    InsightType.BUYING_SIGNAL: BUYING_SIGNAL_RULES,
    InsightType.COMPETITOR_MENTION: COMPETITOR_MENTION_RULES,
    InsightType.NEXT_STEP: NEXT_STEP_RULES,
    InsightType.STALL_TACTIC: STALL_TACTIC_RULES,
}


# ── Engine ─────────────────────────────────────────────────────────────

class InsightEngine:
    """
    Rule-based sales insight detection engine.

    Scans transcript segments against predefined keyword/phrase rules
    and produces structured ``Insight`` objects.
    """

    def __init__(self, window_size: int = 0) -> None:
        """
        Args:
            window_size: If > 0, only analyze the most recent N segments.
                         If 0, analyze all segments (default).
        """
        self.window_size = window_size

    def analyze_segments(
        self,
        segments: list[TranscriptSegment],
        session_id: str = "",
    ) -> SessionInsights:
        """
        Scan segments for sales insights.

        Args:
            segments: Transcript segments to analyze (should be time-ordered).
            session_id: Session identifier for the response.

        Returns:
            SessionInsights with all detected insights and summary counts.
        """
        # Apply sliding window if configured
        target_segments = segments
        if self.window_size > 0 and len(segments) > self.window_size:
            target_segments = segments[-self.window_size:]

        insights: list[Insight] = []
        seen: set[tuple[str, str, float | None]] = set()  # dedup key

        for segment in target_segments:
            text_lower = segment.text.lower()

            for insight_type, rules in _RULE_MAP.items():
                for rule in rules:
                    if rule.phrase in text_lower:
                        # Dedup by (type, phrase, timestamp)
                        dedup_key = (insight_type.value, rule.phrase, segment.timestamp)
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        insight = Insight(
                            type=insight_type,
                            confidence=rule.confidence,
                            matched_text=segment.text,
                            matched_phrase=rule.phrase,
                            speaker=segment.speaker,
                            timestamp=segment.timestamp,
                            suggestion=rule.suggestion,
                        )
                        insights.append(insight)

        # Sort by timestamp, then by confidence descending
        insights.sort(key=lambda i: (i.timestamp or 0, -i.confidence))

        # Build summary counts
        type_counts = Counter(i.type.value for i in insights)

        logger.info(
            "Insight analysis complete | session=%s | segments_scanned=%d | insights_found=%d",
            session_id,
            len(target_segments),
            len(insights),
        )

        return SessionInsights(
            session_id=session_id,
            insights=insights,
            total_insights=len(insights),
            summary=dict(type_counts),
        )


# ── Module-level singleton ────────────────────────────────────────────
insight_engine = InsightEngine(window_size=0)
