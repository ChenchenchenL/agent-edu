"""Quiz observability service for Phase 8 API endpoints.

Provides learner-facing and operator-facing observability queries for quiz
attempts, mastery, misconceptions, and learning gains.

Architecture:
    route (thin) -> service (orchestration + in-memory aggregation) -> repository (SQL)

Aggregation of JSON-typed fields (``misconception_codes``, ``outcome_signals``)
is done in Python for DB-agnostic portability. Both aggregation methods consume
bounded sample sets (``limit``) so memory stays predictable; callers should
treat the results as *windowed estimates*, not global truths.
"""

from __future__ import annotations

import logging
from collections import Counter

from agent_core.domain.schemas.quiz import (
    AdaptivePolicyAuditRecord,
    LearningGainRecord,
    MisconceptionTrendRecord,
    ObservabilityAttemptRecord,
    RecommendedNextActionResponse,
    TopicMasteryResponse,
)
from agent_core.infrastructure.db.repositories import (
    AuditRepository,
    LearnerTopicMasteryRepository,
    SessionQuizAnswerAttemptRepository,
    SessionQuizRepository,
    SessionRepository,
    SkillUsageEventRepository,
)

_LOGGER = logging.getLogger(__name__)


class QuizObservabilityService:
    """Service layer for quiz observability queries."""

    def __init__(
        self,
        *,
        attempt_repository: SessionQuizAnswerAttemptRepository,
        topic_mastery_repository: LearnerTopicMasteryRepository,
        audit_repository: AuditRepository,
        skill_usage_repository: SkillUsageEventRepository,
        quiz_repository: SessionQuizRepository,
        session_repository: SessionRepository,
    ) -> None:
        self._attempt_repository = attempt_repository
        self._topic_mastery_repository = topic_mastery_repository
        self._audit_repository = audit_repository
        self._skill_usage_repository = skill_usage_repository
        self._quiz_repository = quiz_repository
        self._session_repository = session_repository

    # ------------------------------------------------------------------ #
    # Learner-facing
    # ------------------------------------------------------------------ #

    async def get_learner_attempt_history(
        self,
        *,
        learner_profile_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ObservabilityAttemptRecord]:
        attempts = await self._attempt_repository.list_by_learner(
            learner_profile_id=learner_profile_id,
            limit=limit,
            offset=offset,
        )
        return [_attempt_to_record(a) for a in attempts]

    async def get_learner_topic_mastery(
        self,
        *,
        learner_profile_id: str,
        topic_key: str,
    ) -> TopicMasteryResponse:
        mastery = await self._topic_mastery_repository.get_by_profile_and_topic(
            learner_profile_id=learner_profile_id,
            topic_key=topic_key,
        )
        if mastery is None:
            return TopicMasteryResponse(
                topic_key=topic_key,
                mastery_score=0.0,
                confidence=0.0,
                evidence_count=0,
            )
        return TopicMasteryResponse(
            topic_key=mastery.topic_key,
            mastery_score=mastery.mastery_score,
            confidence=mastery.confidence,
            evidence_count=mastery.evidence_count,
        )

    async def get_learner_next_action(
        self,
        *,
        learner_profile_id: str,
    ) -> RecommendedNextActionResponse:
        latest = await self._attempt_repository.get_latest_by_learner(
            learner_profile_id
        )
        action, rationale = _resolve_next_action(latest)
        return RecommendedNextActionResponse(
            recommended_next_action=action,
            rationale=rationale,
        )

    async def get_quiz_adaptation_rationale(
        self,
        *,
        learner_profile_id: str,
        quiz_id: str,
    ) -> str | None:
        stored_quiz = await self._quiz_repository.get_quiz_by_id(quiz_id)
        if stored_quiz is None:
            return None
        session = await self._session_repository.get_by_id(stored_quiz.session_id)
        if session is None or session.learner_profile_id != learner_profile_id:
            return None

        audit_event = await self._audit_repository.get_by_resource(
            resource_id=quiz_id, event_type="quiz.generated"
        )
        if audit_event is not None and isinstance(audit_event.event_data, dict):
            rationale = audit_event.event_data.get("adaptation_rationale")
            if isinstance(rationale, str) and rationale.strip():
                return rationale
        return None

    # ------------------------------------------------------------------ #
    # Operator-facing
    # ------------------------------------------------------------------ #

    async def browse_operator_attempts(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ObservabilityAttemptRecord], int]:
        attempts = await self._attempt_repository.list_recent(limit=limit, offset=offset)
        total_count = await self._attempt_repository.count_all()
        return [_attempt_to_record(a) for a in attempts], total_count

    async def get_operator_grading_queue(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ObservabilityAttemptRecord]:
        attempts = await self._attempt_repository.list_needs_review(
            limit=limit, offset=offset
        )
        return [_attempt_to_record(a) for a in attempts]

    async def get_operator_misconception_trend(
        self,
        *,
        limit: int = 1000,
    ) -> list[MisconceptionTrendRecord]:
        """Windowed misconception frequency over the most recent ``limit`` attempts.

        JSON-array iteration is done in Python for DB-agnostic portability;
        ``limit`` is bounded (max 10000) so memory stays predictable.
        """
        attempts = await self._attempt_repository.list_recent(limit=limit)
        counter: Counter[str] = Counter()
        for attempt in attempts:
            for code in attempt.misconception_codes or ():
                if code:
                    counter[code] += 1
        return [
            MisconceptionTrendRecord(misconception_code=code, count=count)
            for code, count in counter.most_common()
        ]

    async def get_operator_adaptive_policy_audit(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdaptivePolicyAuditRecord]:
        events = await self._audit_repository.list_quiz_adaptive_policy_trail(
            limit=limit, offset=offset
        )
        return [
            AdaptivePolicyAuditRecord(
                id=event.id,
                event_type=event.event_type,
                resource_id=event.resource_id,
                event_data=event.event_data or {},
                created_at=event.created_at,
            )
            for event in events
        ]

    async def get_operator_learning_gain_dashboard(
        self,
        *,
        limit: int = 1000,
    ) -> list[LearningGainRecord]:
        """Windowed average learning gain per skill over the most recent ``limit`` usage events.

        Aggregation is in Python because ``outcome_signals`` is a JSON column;
        ``limit`` is bounded (max 10000) to keep memory predictable.
        """
        events = await self._skill_usage_repository.list_events(limit=limit)
        gains: dict[str, list[float]] = {}
        for event in events:
            signals = event.outcome_signals or {}
            delta = signals.get("mastery_delta")
            before = signals.get("mastery_before")
            after = signals.get("mastery_after")
            if before is not None and after is not None:
                try:
                    delta = float(after) - float(before)
                except (TypeError, ValueError):
                    delta = None
            if delta is None:
                continue
            try:
                delta_value = float(delta)
            except (TypeError, ValueError):
                continue
            gains.setdefault(event.skill_name, []).append(delta_value)

        return [
            LearningGainRecord(
                skill_name=name,
                average_learning_gain=sum(deltas) / len(deltas) if deltas else 0.0,
                sample_size=len(deltas),
            )
            for name, deltas in gains.items()
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attempt_to_record(attempt) -> ObservabilityAttemptRecord:
    return ObservabilityAttemptRecord(
        id=attempt.id,
        session_id=attempt.session_id,
        quiz_id=attempt.quiz_id,
        question_id=attempt.question_id,
        score=attempt.score,
        is_correct=attempt.is_correct,
        misconception_codes=list(attempt.misconception_codes or ()),
        created_at=attempt.created_at,
    )


_NEXT_ACTION_REVIEW_SCHEDULING = "review_scheduling"
_NEXT_ACTION_GENERATE_QUIZ = "generate_quiz"

_RATIONALE_REVIEW_SCHEDULING = (
    "Based on your latest wrong answer, a review session is recommended."
)
_RATIONALE_GENERATE_QUIZ_SUCCESS = (
    "Great job on your latest attempt! Try another quiz to reinforce mastery."
)
_RATIONALE_GENERATE_QUIZ_START = (
    "Start your learning journey by generating a quiz."
)


def _resolve_next_action(latest_attempt) -> tuple[str, str]:
    """Resolve the high-level next-action recommendation for the observability API.

    This rule set is intentionally simpler (two outcomes) than the
    ``_RecommendedNextActionPolicy`` used at attempt submission, which
    returns granular per-attempt actions. The observability endpoint
    provides high-level scheduling guidance.
    """
    if latest_attempt is None:
        return _NEXT_ACTION_GENERATE_QUIZ, _RATIONALE_GENERATE_QUIZ_START
    if latest_attempt.is_correct is False:
        return _NEXT_ACTION_REVIEW_SCHEDULING, _RATIONALE_REVIEW_SCHEDULING
    return _NEXT_ACTION_GENERATE_QUIZ, _RATIONALE_GENERATE_QUIZ_SUCCESS
