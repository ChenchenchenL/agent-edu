"""Pure reflection outcome evaluation policy.

Deterministic and side-effect free: no repository access, no audit writes,
no session dependencies.  Provides the evaluation rules as stable, testable
pure functions so that the status / score / note / snapshot contract can be
regression-tested independently of I/O infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Public constants (the single source of truth for thresholds)
# ---------------------------------------------------------------------------

WINDOW_SIZE_DEFAULT: int = 3
"""Minimum number of topic-filtered attempts required for a non-pending verdict."""

EFFECTIVE_SUCCESS_MIN: int = 2
EFFECTIVE_FAILURE_MAX: int = 1
INEFFECTIVE_FAILURE_MIN: int = 2

EFFECTIVE_SCORE: float = 0.7
INEFFECTIVE_SCORE: float = -0.5
INCONCLUSIVE_SCORE: float = 0.0

EFFECTIVE_NOTE: str = "follow-up attempts improved"
INEFFECTIVE_NOTE: str = "follow-up attempts did not improve"
INCONCLUSIVE_NOTE: str = "mixed follow-up results"
PENDING_NOTE: str = "insufficient evidence"

FEEDBACK_EFFECTIVE_PRIORITY_DELTA: float = 0.1
FEEDBACK_INEFFECTIVE_PRIORITY_DELTA: float = 0.15

# Threshold for creating a skill_package proposal from an effective reflection.
SKILL_PACKAGE_DUPLICATE_MIN: int = 1
SKILL_PACKAGE_PRIORITY_THRESHOLD: float = 0.7


# ---------------------------------------------------------------------------
# Lightweight protocol used only for type-checking in evaluate_outcome
# ---------------------------------------------------------------------------


class AttemptLike(Protocol):
    """Minimal protocol for a task attempt record."""

    id: str
    outcome_status: str


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeEvaluationResult:
    """Deterministic result of evaluating reflection outcome evidence.

    Mirrors the persisted fields on ``ReflectionOutcomeEvaluation`` that are
    written by ``ReflectionOutcomeService.evaluate()``.
    """

    evaluation_status: str
    """One of 'pending' | 'effective' | 'ineffective' | 'inconclusive'."""
    improvement_score: float
    evaluation_note: str
    observed_attempt_count: int
    outcome_snapshot: dict[str, Any]
    evaluated: bool
    """True when a concrete verdict (not merely pending) was reached."""


# ---------------------------------------------------------------------------
# Core pure evaluation function
# ---------------------------------------------------------------------------


def evaluate_outcome(
    *,
    topic_attempts: list[Any],
    window_size: int = WINDOW_SIZE_DEFAULT,
) -> OutcomeEvaluationResult:
    """Evaluate reflection outcome from topic-filtered task attempts.

    This is a pure distillation of the heuristic logic in
    ``ReflectionOutcomeService.evaluate()``.  It is intentionally separated
    so quality rules can be regression-tested without any I/O.

    Args:
        topic_attempts: Task attempts already filtered to the relevant topic.
            Each item must expose ``id`` (str) and ``outcome_status`` (str).
        window_size: Minimum attempts required to issue a non-pending verdict.
            Defaults to ``WINDOW_SIZE_DEFAULT`` (3).

    Returns:
        An ``OutcomeEvaluationResult`` describing the evaluation verdict.
    """
    if not topic_attempts:
        return OutcomeEvaluationResult(
            evaluation_status="inconclusive",
            improvement_score=INCONCLUSIVE_SCORE,
            evaluation_note=PENDING_NOTE,
            observed_attempt_count=0,
            outcome_snapshot={"success_count": 0, "failure_count": 0, "attempt_ids": []},
            evaluated=False,
        )

    success_count = sum(1 for a in topic_attempts if _outcome(a) == "completed")
    failure_count = sum(1 for a in topic_attempts if _outcome(a) in {"failed", "skipped"})
    attempt_ids = [_attempt_id(a) for a in topic_attempts]

    snapshot: dict[str, Any] = {
        "success_count": success_count,
        "failure_count": failure_count,
        "attempt_ids": attempt_ids,
    }

    if len(topic_attempts) < window_size:
        return OutcomeEvaluationResult(
            evaluation_status="inconclusive",
            improvement_score=INCONCLUSIVE_SCORE,
            evaluation_note=PENDING_NOTE,
            observed_attempt_count=len(topic_attempts),
            outcome_snapshot=snapshot,
            evaluated=False,
        )

    if success_count >= EFFECTIVE_SUCCESS_MIN and failure_count <= EFFECTIVE_FAILURE_MAX:
        status = "effective"
        score = EFFECTIVE_SCORE
        note = EFFECTIVE_NOTE
    elif failure_count >= INEFFECTIVE_FAILURE_MIN:
        status = "ineffective"
        score = INEFFECTIVE_SCORE
        note = INEFFECTIVE_NOTE
    else:
        status = "inconclusive"
        score = INCONCLUSIVE_SCORE
        note = INCONCLUSIVE_NOTE

    return OutcomeEvaluationResult(
        evaluation_status=status,
        improvement_score=score,
        evaluation_note=note,
        observed_attempt_count=len(topic_attempts),
        outcome_snapshot=snapshot,
        evaluated=True,
    )


# ---------------------------------------------------------------------------
# Helper predicates used by apply_outcome_feedback and downstream callers
# ---------------------------------------------------------------------------


def requires_feedback(evaluation_status: str) -> bool:
    """Return True if the outcome requires downstream feedback to be applied.

    ``apply_outcome_feedback()`` is a no-op for ``pending`` and
    ``inconclusive`` outcomes.  Only ``effective`` and ``ineffective``
    trigger downstream fan-out.
    """
    return evaluation_status in {"effective", "ineffective"}


def skill_package_eligible(
    *,
    evaluation_status: str,
    duplicate_count: int,
    priority_score: float,
    priority_threshold: float = SKILL_PACKAGE_PRIORITY_THRESHOLD,
    duplicate_min: int = SKILL_PACKAGE_DUPLICATE_MIN,
) -> bool:
    """Return True if a reflection should create skill package proposals.

    This mirrors the condition in ``apply_outcome_feedback()``::

        if updated.duplicate_count >= 1 and updated.priority_score >= 0.7:
            await self._proposal_service.create_skill_packages_from_reflection(...)

    Args:
        evaluation_status: The outcome evaluation status.
        duplicate_count: Number of duplicate reflections seen so far.
        priority_score: Current priority score of the reflection record.
        priority_threshold: Minimum priority required (default 0.7).
        duplicate_min: Minimum duplicate count required (default 1).
    """
    return (
        evaluation_status == "effective"
        and duplicate_count >= duplicate_min
        and priority_score >= priority_threshold
    )


def feedback_priority_delta(evaluation_status: str) -> float:
    """Return how much the reflection priority_score increases after feedback.

    Intentionally ``ineffective > effective`` to escalate unresolved issues
    faster than confirmed improvements.
    """
    if evaluation_status == "effective":
        return FEEDBACK_EFFECTIVE_PRIORITY_DELTA
    if evaluation_status == "ineffective":
        return FEEDBACK_INEFFECTIVE_PRIORITY_DELTA
    return 0.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _outcome(attempt: Any) -> str:
    return str(getattr(attempt, "outcome_status", ""))


def _attempt_id(attempt: Any) -> str:
    return str(getattr(attempt, "id", ""))
